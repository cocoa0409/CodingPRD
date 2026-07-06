# Short-Term Rental API — Product Requirements Document

## 1. Introduction

Cities that permit short-term rentals face a persistent enforcement problem: a finite housing stock, a limited number of legal rental slots per neighborhood, and a sprawling long tail of listings advertised on booking platforms that may or may not correspond to a lawfully registered property. This document specifies the backend service that a municipal short-term-rental office uses to administer that program end to end — registering hosts and their properties, issuing and revoking rental permits against a per-district density cap, collecting the transient-occupancy tax (TOT) owed on lodging revenue, reconciling platform-reported listings against the permit registry, and processing nuisance complaints that can suspend or revoke a permit and ultimately bar a repeat-offending host.

The service is organized around the **Permit** as the primary lifecycle resource, mounted under `/permits`, with peer collections for zones, hosts, properties, tax filings, listing reports, complaints, and lottery rounds referenced by explicit foreign keys. Four distinct actors interact with the system — a city registrar who administers eligibility and enforcement, a tax officer who runs revenue collection, hosts who own the underlying properties, and data-sharing platforms that feed listing rows for reconciliation. Because permit availability is a scarce, regulated resource and tax dollars are at stake, the service must be exacting about eligibility rules, cap arithmetic, tax computation, and the ordering of concurrent writes; the sections that follow define those contracts precisely and then narrate the workflows that weave them together.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request (with a single exception noted below) must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role under which the request is made. If either header is missing, or if `X-User-Role` is not one of the declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The one exception is the logical-clock endpoint, which is open to both the `CityRegistrar` and `TaxOfficer` roles but still requires valid headers.

The system recognizes exactly four roles, spelled precisely: `CityRegistrar`, `TaxOfficer`, `Host`, and `Platform`. When a request presents valid headers but the acting role is not permitted to perform the requested operation — or an entity-backed role attempts to act on a resource it does not own where ownership is required — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Two of the roles are opaque operator identities and two are entity-backed. When `X-User-Role` is `CityRegistrar`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and record it but does not compare it to any entity's `id`. Likewise, when `X-User-Role` is `TaxOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is never matched against an entity's `id`. When `X-User-Role` is `Host`, `X-User-ID` is the `id` of the acting `Host`; ownership checks on any resource that references a `Host` compare the resource's host foreign key to `X-User-ID` — for example, a host activating or renewing a permit must be the permit's owner, and a host remitting a tax filing must own the permit that filing reports against. When `X-User-Role` is `Platform`, `X-User-ID` is the `id` of the acting `Platform` (the server-minted `api_key` the platform presents); ownership checks on any resource that references a `Platform` compare the resource's platform foreign key to `X-User-ID`, and a platform's own `api_key` or its persisted `id` are both accepted as a matching `X-User-ID` for that platform.

The `CityRegistrar` administers zones, hosts, properties, permits, complaints, lotteries, and platforms — issuing, rejecting, and reinstating permits, dismissing and upholding complaints, opening and drawing lottery rounds, registering platforms, and viewing platform keys. The `TaxOfficer` manages TOT filings and their remittance status — filing and amending — and is read-only elsewhere, and specifically may not read a platform's key. A `Host` registers properties and permits, attests a primary residence, activates and renews their own permits, and remits taxes on their own permits. A `Platform` submits listing reports for reconciliation and does nothing else.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

### 2.3. Pagination

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, has a minimum of 1, and a maximum of 100; a supplied value outside that range is rejected as an invalid request. The `offset` parameter defaults to 0 and has a minimum of 0. Results on every list endpoint are ordered by `created_at` ascending. The `meta` block on a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the total number of matching records before pagination and `has_more` indicates whether records remain beyond the current page.

### 2.4. Common Resource Properties

Most resources carry a common set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits, `created_at` being fixed at creation and `updated_at` refreshed on every mutation. The `version` field is an integer that begins at its initial value on creation and increments by one on every successful mutation of the resource; it is the value used for optimistic concurrency control (§2.7).

One entity is an exception. The **ListingReport** is an append-only reconciliation event: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, and it is never mutated after creation — these two fields are absent from its representation entirely.

### 2.5. The Logical Clock and Time-Driven Auto-Transitions

The service runs on a logical clock rather than wall-clock time. At server startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any clock is set it continues to read exactly this default and never falls back to real wall-clock time. A privileged capability lets an operator set the clock to a supplied `to_iso8601` instant; advancing the clock is how the test harness makes time-driven transitions observable.

Two transitions are time-driven and are evaluated lazily — that is, whenever a read or mutation touches the affected resource. A permit in `ISSUED` or `ACTIVE` status whose `expires_at` is at or before the current clock time auto-transitions to `EXPIRED` on the next touch; because an expired permit no longer occupies a density seat, this also decrements its zone's active permit count. A tax filing in `FILED` status whose `due_at` is at or before the current clock time and which remains underpaid auto-transitions to `DELINQUENT` on the next touch, at which point its late penalty is computed and frozen. These lazy transitions must be applied before the rest of a request's logic runs, so that, for example, a renewal request against a permit that has just expired sees the `EXPIRED` state rather than the stale `ACTIVE` one.

### 2.6. Cascading Consistency and Density Accounting

Several operations mutate more than one resource, and every such cascade must be applied atomically. Each zone tracks a computed `active_permit_count`, defined as the number of permits foreign-key-linked to that zone whose status is either `ACTIVE` or `SUSPENDED`; however, for the purpose of the density cap this count also includes `ISSUED` permits, because an issued-but-not-yet-activated permit still occupies a seat. Concretely, issuing a permit into `ISSUED` (or awarding it through a lottery) increments the zone's active permit count by one, while any transition that removes a permit from the occupying set — revocation or expiry — decrements it by one. Whenever a permit's status changes as part of a cascade, that permit's `updated_at` is refreshed and its `version` is incremented; the same holds for any complaint, host, filing, or zone whose fields a cascade writes.

The deepest cascade in the system originates from upholding a complaint. Upholding assigns the complaint's strike points, then recomputes the target permit's cumulative upheld strike total, which may suspend or revoke the permit (and, on revocation, release its zone seat), and finally recomputes the owning host's aggregate strike total and standing. Each entity touched along that chain has its `version` bumped and `updated_at` refreshed.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control. A renewal request must carry `expected_permit_version`, which must equal the target permit's current `version` — the value the client last observed. Renewal legitimately re-anchors the permit's expiry and bumps its version; if the permit's version has advanced since the client last read it (for instance because an earlier renewal already ran), the `expected_permit_version` the client sends is stale, and the renewal is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from re-applying a change against a permit it has not observed. A drawing request against a lottery round must carry `expected_lottery_round_version`, which must equal that round's current `version`; if the round's version has advanced since the client last read it — for example because entrants were added and an amendment advanced the round — the draw is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than silently drawing against a different pool of entrants. No other endpoint accepts a version field. On both guarded operations the version guard is evaluated as a business rule, after the target's state check (§2.9): if the requested transition is not defined from the target's current state, `ERR_INVALID_STATE` (HTTP 409) is returned before the version is compared, so a second draw against an already-`DRAWN` round yields `ERR_INVALID_STATE` and never `ERR_STALE_VERSION`.

### 2.8. Precision, Rounding, and Money

All monetary quantities are stored and computed in integer cents. Wherever a computation produces a fractional cent, it is resolved by rounding half up to the nearest whole cent. The section-3 narratives that define the tax and penalty computations state exactly where in each computation a rounding step occurs; the order of those rounding steps is part of the contract and must be honored, because rounding a per-line component before summing yields a different total than summing before rounding.

### 2.9. Request Validation and Left-to-Right Reference Resolution

Every create and transition request is subject to a fixed order of checks, and the first check that fails determines the error returned. Authentication (§2.1) is evaluated first, then role and ownership authorization, then existence of every referenced resource. Reference resolution is performed left-to-right in the order Zone, Host, Property, Permit, TaxFiling, Complaint, LotteryRound, Platform; any path or body foreign key that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404). Only after references resolve is the target's state checked: if the requested transition is not defined from the resource's current state, the request is rejected with `ERR_INVALID_STATE` (HTTP 409). Domain-specific business rules — eligibility, safety, caps, windows, and so on — are evaluated after the state check, in the priority order the relevant §3 narratives spell out. Finally, on any POST, PUT, or PATCH, the request body must supply all required fields with valid types, enum members, and ranges; a malformed body yields `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Zones and the Density Regime

A city registrar defines the map of the program by creating zoning districts. A zone carries a `zone_code`, a unique zoning-district code such as "R1"; a create request supplying a `zone_code` that already exists is rejected with `ERR_DUPLICATE_ZONE_CODE` (HTTP 409). Three booleans configure the zone's policy: `str_eligible` indicates whether short-term rentals are permitted at all in the district and defaults to true; `whole_home_allowed` indicates whether non-primary-residence (whole-home) permits may be issued there and defaults to false, meaning that unless a zone opts in, only primary-residence permits may issue; and `lottery_enabled`, defaulting to false, controls what happens when a permit application arrives at a full zone. The zone's `permit_cap` is the maximum number of permits the district may hold in the occupying set at once, and must be at least zero. The zone also exposes a computed `active_permit_count`, defaulting to zero, which counts the permits linked to the zone whose status is `ISSUED`, `ACTIVE`, or `SUSPENDED` — the same occupying set the density cap uses (§2.6), including `ISSUED` permits; fetching a zone recomputes this count from the zone's linked permits over that `ISSUED`/`ACTIVE`/`SUSPENDED` set before returning it.

### 3.2. Hosts, Properties, and the Primary-Residence Attestation

A host is registered with an `email` and a `full_name`. The `email` must be unique across all hosts; a duplicate is rejected with `ERR_DUPLICATE_EMAIL` (HTTP 409). Each host also exposes `primary_residence_property_id`, a foreign key to the single property the host has attested as their primary residence, which is null until set; a computed `strike_total`, defaulting to zero; and a computed `standing`, defaulting to `GOOD`.

A property is registered under a host and a zone, carrying `host_id`, `zone_id`, and a `street_address` that must be unique across all properties — a duplicate address is rejected with `ERR_DUPLICATE_ADDRESS` (HTTP 409). Its `bedroom_count` must be at least one and drives occupancy: at creation the system computes the property's `max_occupancy` as twice the bedroom count plus one, reflecting an allowance of two occupants per bedroom plus one for common areas. The property also carries `is_primary_residence`, a system flag defaulting to false that becomes true precisely when this property is the one recorded as its host's primary residence.

A host designates their primary residence by an attestation that supplies a `property_id`. The attestation sets the host's `primary_residence_property_id` to that property, flips that property's `is_primary_residence` to true, and increments the host's `version`. A host may hold at most one primary residence; if the host already has a primary residence set to a different property, attempting to set a second is rejected with `ERR_PRIMARY_RESIDENCE_CONFLICT` (HTTP 409). Re-attesting the same property the host has already recorded as its primary residence is idempotent: it is not a conflict, it re-affirms that property's `is_primary_residence` flag, and it leaves the host's `version` unchanged.

### 3.3. Filing a Permit Application

A permit application is created against a property, supplying `property_id`, a `permit_type`, an `attested_occupancy`, an optional `safety_attested` flag, and a `nightly_base_rate_cents`. The `permit_type` is one of `PRIMARY_RESIDENCE` or `WHOLE_HOME`. The `attested_occupancy` is the host-attested maximum number of guests. The `safety_attested` flag records whether the host affirmed the safety attestation covering smoke and carbon-monoxide detectors and egress, and defaults to false. The `nightly_base_rate_cents` is the advertised nightly rate in cents that will serve as the tax base per night, and must be at least zero. At creation the permit denormalizes `host_id` from the property's owning host and `zone_id` from the property's zone, and begins life in `DRAFT` status. The permit also carries system-managed fields populated later in its lifecycle: `issued_at`, the logical-clock instant it became issued, null while in `DRAFT`, `REJECTED`, or `LOTTERY_PENDING`; `expires_at`, the computed expiry; and `status` itself, whose full set of values is `DRAFT`, `LOTTERY_PENDING`, `ISSUED`, `ACTIVE`, `SUSPENDED`, `REVOKED`, `EXPIRED`, and `REJECTED`.

### 3.4. Issuance: Eligibility, Safety, and the Cap Gate

When a registrar issues a `DRAFT` permit, a sequence of gates is evaluated, and the ordering matters because the first failing gate determines the response. The zoning gate comes first: the referenced property's zone must be short-term-rental eligible, and if its `str_eligible` is false the issue is rejected with `ERR_ZONE_INELIGIBLE` (HTTP 422). Next the whole-home gate: if the `permit_type` is `WHOLE_HOME`, the zone's `whole_home_allowed` must be true, otherwise the issue is rejected with `ERR_WHOLE_HOME_FORBIDDEN` (HTTP 422). Next the residence gate: if the `permit_type` is `PRIMARY_RESIDENCE`, the property must be the host's primary residence (its `is_primary_residence` must be true), otherwise the issue is rejected with `ERR_NOT_PRIMARY_RESIDENCE` (HTTP 422). Next the safety gate: `safety_attested` must be true, otherwise `ERR_SAFETY_NOT_ATTESTED` (HTTP 422). Next the occupancy gate: `attested_occupancy` must be at least one and at most the property's `max_occupancy`, otherwise `ERR_OCCUPANCY_EXCEEDS_MAX` (HTTP 422). Next the standing gate: the owning host's `standing` must be `GOOD`, otherwise `ERR_HOST_BARRED` (HTTP 422).

The final gate is the density cap. If the zone's active permit count is below its `permit_cap`, the permit is issued: it transitions from `DRAFT` to `ISSUED`, `issued_at` is set to the current clock time, `expires_at` is set to `issued_at` plus 365 days, the zone's active permit count is incremented by one (an `ISSUED` permit counts toward the cap alongside `ACTIVE` and `SUSPENDED` ones), and the permit's `version` is incremented. If instead the zone's active permit count is at or beyond the `permit_cap`, behavior forks on the zone's `lottery_enabled` flag: when lottery is enabled, the same issue attempt — having passed every gate above except the cap — instead lands the permit in `LOTTERY_PENDING` and increments the permit's `version`, and crucially does **not** change the zone's active permit count, since a pending entrant does not yet occupy a seat; when lottery is disabled, the issue is rejected with `ERR_PERMIT_CAP_REACHED` (HTTP 422). A registrar may also reject a `DRAFT` permit outright, moving it to `REJECTED` and incrementing its `version`.

### 3.5. The Lottery Waterfall

When a zone runs on lottery allocation, the registrar opens a lottery round for a zone with a fixed seat pool, supplying `zone_id` and `seats_available` (which must be at least zero). The round begins in `OPEN` status and exposes `awarded_permit_ids`, initially empty, plus its own `status`, which moves `OPEN` to `DRAWN`, a terminal state. Drawing the round is a version-guarded operation: the draw request carries `expected_lottery_round_version`, and the draw runs only if that value matches the round's current `version`, failing otherwise with `ERR_STALE_VERSION` (HTTP 412) as described in §2.7.

On a successful draw, the round's `LOTTERY_PENDING` permits are ordered by their `created_at` ascending (using creation time, never id, as the ordering key). The first `seats_available` of them are awarded: each awarded permit transitions from `LOTTERY_PENDING` to `ISSUED`, receives an `issued_at` of the current clock time and an `expires_at` of `issued_at` plus 365 days, increments the zone's active permit count by one per award, and increments its own `version`. Every remaining, unseated `LOTTERY_PENDING` permit transitions to `REJECTED` and increments its `version`. The round records the ordered list of awarded permit ids in `awarded_permit_ids`, sets its `status` to `DRAWN`, and increments its own `version`. Equivalently, a single pending permit is later brought to `ISSUED` if and only if it sits among the first `seats_available` entrants by creation time, and to `REJECTED` if it does not.

### 3.6. Activation, Renewal, Expiry, and the Enforcement Ladder

Once a permit is `ISSUED`, its owning host activates it for operation, moving it from `ISSUED` to `ACTIVE` and incrementing its `version`; only the host whose id matches the permit's owner may do so, and a mismatch is an ownership failure. Activation presumes the permit has not expired: if the clock has reached `expires_at`, the permit auto-transitions to `EXPIRED` first (see §2.5) and the activation then fails against that terminal state.

An `ACTIVE` permit may be renewed by its owning host within a narrow window. Renewal is permitted only when the current clock time is at or after `expires_at` minus 30 days and strictly before `expires_at`; outside that window the renewal is rejected with `ERR_RENEWAL_WINDOW_CLOSED` (HTTP 422). Renewal further requires that the owning host still be in `GOOD` standing, failing with `ERR_HOST_BARRED` (HTTP 422) otherwise, and that the supplied `expected_permit_version` match the permit's current `version` per §2.7. A successful renewal extends `expires_at` by 365 days from the existing anchor — not from the current clock time — and increments the permit's `version`; it is a self-loop on the `ACTIVE` state and does not touch the zone's active permit count. A permit in `ISSUED` or `ACTIVE` status whose `expires_at` has been reached auto-transitions to `EXPIRED` on the next touch and, as part of that transition, decrements its zone's active permit count and increments its own `version`.

Complaints drive the enforcement ladder. Cumulative upheld strike points accrued against a single permit determine its fate: when the permit's own cumulative upheld strike total reaches two but stays below four while the permit is `ACTIVE`, the system moves it from `ACTIVE` to `SUSPENDED` and increments its `version`. A registrar may later reinstate a `SUSPENDED` permit — provided its cumulative upheld strike total is still below four — moving it from `SUSPENDED` back to `ACTIVE` and incrementing its `version`; a permit that has reached four is beyond reinstatement and a reinstate attempt against it is rejected with `ERR_INVALID_STATE` (HTTP 409). When the cumulative upheld strike total reaches four, the permit is revoked: from `ACTIVE` (or from `SUSPENDED`) it moves to `REVOKED`, its zone's active permit count is decremented by one to free the density seat, and its `version` is incremented. The terminal states of a permit are `REVOKED`, `EXPIRED`, and `REJECTED`.

### 3.7. Complaints and Host Standing

Anyone with standing to report — a registrar or a host — files a nuisance complaint against a permit, supplying `permit_id` and a `category` drawn from `NOISE`, `TRASH`, `OVER_OCCUPANCY`, or `UNPERMITTED`. The complaint opens in `OPEN` status with `strike_points` of zero, and moves to one of two terminal states, `DISMISSED` or `UPHELD`. A registrar dismisses an `OPEN` complaint, in which case its `strike_points` remains zero and its `version` increments. Upholding is the consequential path and is available only when the target permit is currently enforceable — that is, in `ISSUED`, `ACTIVE`, or `SUSPENDED` status; upholding against a permit outside that set is rejected with `ERR_PERMIT_NOT_ENFORCEABLE` (HTTP 422).

Upon a successful uphold, the complaint's `strike_points` is set according to severity: complaints in category `NOISE` or `TRASH` carry one point, while `OVER_OCCUPANCY` or `UNPERMITTED` complaints carry two. The system then recomputes the target permit's cumulative upheld strike total over the upheld complaints filed against that same permit, and applies the enforcement ladder of §3.6 — suspension at a cumulative total of two (while below four and `ACTIVE`), revocation with seat release at four. As a second hop, it recomputes the owning host's aggregate risk. The host's `strike_total` is the sum of `strike_points` across every `UPHELD` complaint on every permit that host owns — open and dismissed complaints contribute nothing. The host's `standing` is `GOOD` while that aggregate is strictly below three and becomes `BARRED` once it reaches three; a `BARRED` host cannot receive newly issued permits and cannot renew. The complaint's own `version` is incremented, and every permit, zone, and host touched along the cascade has its `updated_at` refreshed and its `version` bumped. Note the two strike computations use different scopes and thresholds: the permit-level suspend/revoke decision sums only the upheld complaints against that one permit and triggers at two and four, whereas the host-level standing sums the upheld complaints across all of that host's permits and triggers at three.

### 3.8. Transient-Occupancy-Tax Filing, Amendment, and Remittance

A tax filing reports lodging revenue for one permit over one calendar month. It is created with `permit_id`, `period_year`, `period_month` (a month from 1 through 12), `nights_booked`, and `gross_revenue_cents`, both of the latter being at least zero. The triple of permit, year, and month must be unique; a second filing for an already-filed period is rejected with `ERR_DUPLICATE_FILING_PERIOD` (HTTP 409). The filing opens in `DRAFT` and carries computed fields populated over its life: `tot_due_cents`, the tax owed; `penalty_cents`, a late penalty defaulting to zero; `amount_remitted_cents`, the cumulative amount paid, defaulting to zero; `due_at`, the remittance deadline; and `status`, whose values are `DRAFT`, `FILED`, `REMITTED`, and `DELINQUENT`.

A tax officer files a `DRAFT` filing. Two business rules gate the file, evaluated in this order so that the first failing gate determines the response. First, filing requires `nights_booked` to be at least one, since a zero-night period has nothing to file; a zero-night filing is rejected with `ERR_NO_NIGHTS_TO_FILE` (HTTP 422). Second, filing requires that the target permit be in a fileable state — a filing may report revenue even for a permit that has since been issued, activated, suspended, expired, or revoked, and only permits still in `DRAFT`, `REJECTED`, or `LOTTERY_PENDING` cannot be filed against, which is rejected with `ERR_PERMIT_NOT_FILEABLE` (HTTP 422). On a successful file, the system computes `tot_due_cents` (below), sets `due_at` to the last calendar day of the reported period at `00:00:00Z` plus 30 days, moves the filing from `DRAFT` to `FILED`, and increments its `version`.

The tax is a two-tier transient-occupancy tax combining a marginal percentage on gross revenue with a flat per-night lodging fee. The percentage rates are 8.00% base and 12.00% surge, applied around a tier boundary of 14 nights: the first 14 nights of a period are taxed at the base rate and any nights beyond that at the surge rate. The flat fee is 300 cents ($3.00) per night. The computation is order-pinned as follows. First compute the percentage component to whole cents. If `nights_booked` is at most 14, the percentage component is the gross revenue multiplied by 8%, rounded half up to whole cents. If `nights_booked` exceeds 14, the revenue is apportioned per night — the exact per-night revenue is the gross revenue divided by the number of nights, kept as an exact rational without rounding — and two shares are formed and each rounded half up to whole cents independently: a base share of the per-night revenue times 14 times 8%, and a surge share of the per-night revenue times the number of nights beyond 14 times 12%; the percentage component is the sum of those two rounded shares. Then compute the flat component as the number of nights booked times 300 cents, which is exact. The `tot_due_cents` is the percentage component plus the flat component. The percentage components are each rounded to whole cents before they are summed with each other and with the flat fee; the flat fee itself is an exact integer.

A tax officer may re-open a `FILED` filing for correction, but only if no money has yet been paid against it — `amount_remitted_cents` must be zero, otherwise the amendment is rejected with `ERR_FILING_HAS_REMITTANCES` (HTTP 422). A successful amendment moves the filing from `FILED` back to `DRAFT`, resets both `tot_due_cents` and `due_at` to null, and increments the filing's `version`; the officer can then correct and re-file.

The owning host remits payment against a `FILED` or `DELINQUENT` filing, supplying `payment_cents` (which must be at least zero); only the host who owns the permit the filing reports against may remit. Each remittance increments `amount_remitted_cents` by the `payment_cents` and increments the filing's `version`. From `FILED`, if the current clock time is before `due_at` and the cumulative `amount_remitted_cents` after this payment reaches or exceeds `tot_due_cents`, the filing transitions to `REMITTED`; if the payment is only partial it is recorded and the filing remains `FILED` with no error raised. If the clock reaches `due_at` while the filing is `FILED` and still underpaid, the filing auto-transitions to `DELINQUENT`, its late penalty is computed and frozen at that instant, and its `version` is incremented. From `DELINQUENT`, a remittance transitions the filing to `REMITTED` only once the cumulative `amount_remitted_cents` reaches or exceeds `tot_due_cents` plus `penalty_cents`; a partial payment is recorded and the filing stays `DELINQUENT`. The single terminal state of a filing is `REMITTED`.

The late penalty is computed once, at the moment of the `DELINQUENT` transition, and its `days_late` input is frozen at that instant rather than recomputed on later reads. It is a flat delinquency fee plus a per-day interest accrual on the unpaid balance, capped at a fraction of that balance. The unpaid balance is `tot_due_cents` minus `amount_remitted_cents`. The number of days late is the whole number of days from `due_at` to the current clock time, rounded down (and non-negative at the transition). The interest is the unpaid balance times a daily rate of 0.50% times the number of days late, rounded half up to whole cents. The raw penalty is a flat 2500 cents ($25) plus that interest. The cap is the unpaid balance times 25%, rounded half up to whole cents. The `penalty_cents` is the lesser of the raw penalty and the cap, with the lesser-of comparison applied only after both the raw penalty and the cap have each been fully computed.

### 3.9. Platform Data-Sharing and Listing Reconciliation

The registrar registers each data-sharing platform by supplying a `platform_name`, which must be unique across all platforms; a create request supplying a `platform_name` that already exists is rejected with `ERR_INVALID_REQUEST` (HTTP 400). On registration the server mints an opaque `api_key`, which the platform later presents as its `X-User-ID` when submitting data-share rows; the registrar can fetch a platform to retrieve this key, but a tax officer cannot.

A platform submits a listing report — an append-only reconciliation row — supplying `platform_id`, an optional `claimed_permit_number` (the permit id string the platform believes the listing displays, which may be blank or unknown), a `street_address` as advertised on the platform, and `reported_nights` (the nights the platform reports booked in the window, at least zero). On submission the server reconciles the row against the permit registry and computes two fields: `match_result`, one of `MATCHED`, `ADDRESS_MISMATCH`, `NO_PERMIT`, or `PERMIT_INACTIVE`; and `matched_permit_id`, the permit the row resolved to, or null when no permit is found.

The reconciliation is order-pinned: identity is resolved first, then status is evaluated on the resolved permit. If `claimed_permit_number` is non-empty and a permit with that id exists, that permit is taken as the resolved permit: if its property's `street_address` equals the report's `street_address`, then the result is `MATCHED` when the permit's status is `ISSUED` or `ACTIVE` and `PERMIT_INACTIVE` for any other status; if the addresses do not agree, the result is `ADDRESS_MISMATCH`. If instead `claimed_permit_number` is blank or unknown or resolves to no permit, the system falls back to address resolution: it gathers the permits whose property's `street_address` equals the report's `street_address`; if there are none, the result is `NO_PERMIT`; otherwise it selects the permit with the latest `issued_at`, breaking ties by `created_at` ascending (never by id), and the result is `MATCHED` when that permit's status is `ISSUED` or `ACTIVE` and `PERMIT_INACTIVE` otherwise. The `matched_permit_id` is set to the resolved permit's id whenever a permit was resolved, and null when the outcome was `NO_PERMIT`.

## 4. Endpoint Definitions

All endpoints share the response envelope of §2.2. Creating a new resource returns HTTP 201; state transitions, attestations, remittances, and other modifications of an existing resource return HTTP 200, as do reads and the clock capability. Request and response payloads are not restated here — reconstruct them from the §3 narratives.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/zones` | Create a zoning district | CityRegistrar |
| GET | `/zones/{id}` | Fetch a zone including computed active permit count | CityRegistrar, TaxOfficer, Host |
| GET | `/zones` | List zones | CityRegistrar, TaxOfficer, Host |
| POST | `/hosts` | Register a host | CityRegistrar, Host |
| GET | `/hosts/{id}` | Fetch a host including computed strike total and standing | CityRegistrar, TaxOfficer, Host |
| POST | `/hosts/{id}/attest-primary-residence` | Set the host's single primary-residence property | Host |
| POST | `/properties` | Register a property under a host and zone | CityRegistrar, Host |
| GET | `/properties/{id}` | Fetch a property | CityRegistrar, TaxOfficer, Host |
| GET | `/properties` | List/filter properties by host or zone | CityRegistrar, TaxOfficer, Host |
| POST | `/permits` | Create a DRAFT permit application for a property | CityRegistrar, Host |
| GET | `/permits/{id}` | Fetch a permit (applies expiry auto-transition) | CityRegistrar, TaxOfficer, Host |
| GET | `/permits` | List/filter permits by property, host, zone, or status | CityRegistrar, TaxOfficer, Host |
| POST | `/permits/{id}/issue` | Issue a DRAFT permit (or route to lottery when the cap is reached) | CityRegistrar |
| POST | `/permits/{id}/reject` | Reject a DRAFT permit | CityRegistrar |
| POST | `/permits/{id}/activate` | Owning host activates an ISSUED permit | Host |
| POST | `/permits/{id}/renew` | Owning host renews an ACTIVE permit within the window (OCC-guarded) | Host |
| POST | `/permits/{id}/reinstate` | Reinstate a SUSPENDED permit to ACTIVE | CityRegistrar |
| POST | `/complaints` | File a nuisance complaint against a permit | CityRegistrar, Host |
| GET | `/complaints/{id}` | Fetch a complaint | CityRegistrar, TaxOfficer, Host |
| GET | `/complaints` | List/filter complaints by permit or status | CityRegistrar, TaxOfficer, Host |
| POST | `/complaints/{id}/dismiss` | Dismiss an OPEN complaint | CityRegistrar |
| POST | `/complaints/{id}/uphold` | Uphold an OPEN complaint (cascades to permit and host) | CityRegistrar |
| POST | `/tax-filings` | Create a DRAFT tax filing for a permit and period | TaxOfficer, Host |
| GET | `/tax-filings/{id}` | Fetch a tax filing (applies delinquency auto-transition) | CityRegistrar, TaxOfficer, Host |
| GET | `/tax-filings` | List/filter tax filings by permit or status | CityRegistrar, TaxOfficer, Host |
| POST | `/tax-filings/{id}/file` | File a DRAFT filing (computes tax and deadline) | TaxOfficer |
| POST | `/tax-filings/{id}/amend` | Re-open a FILED filing with no remittances | TaxOfficer |
| POST | `/tax-filings/{id}/remit` | Owning host remits payment against a filing | Host |
| POST | `/lottery-rounds` | Open a lottery round for a zone with a fixed seat pool | CityRegistrar |
| GET | `/lottery-rounds/{id}` | Fetch a lottery round including awarded permit ids | CityRegistrar, TaxOfficer, Host |
| GET | `/lottery-rounds` | List/filter lottery rounds by zone or status | CityRegistrar, TaxOfficer, Host |
| POST | `/lottery-rounds/{id}/draw` | Draw the round, awarding seats by creation order (OCC-guarded) | CityRegistrar |
| POST | `/platforms` | Register a data-sharing platform (server mints api key) | CityRegistrar |
| GET | `/platforms/{id}` | Fetch a platform including its api key | CityRegistrar |
| POST | `/listing-reports` | Submit a listing data-share row (server computes match) | Platform |
| GET | `/listing-reports/{id}` | Fetch a listing report with its resolved match | CityRegistrar, TaxOfficer |
| GET | `/listing-reports` | List/filter listing reports by platform, matched permit, or result | CityRegistrar, TaxOfficer |
| POST | `/_clock/set_current_utc` | Set the logical clock | CityRegistrar, TaxOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_ZONE_INELIGIBLE | 422 |
| ERR_WHOLE_HOME_FORBIDDEN | 422 |
| ERR_NOT_PRIMARY_RESIDENCE | 422 |
| ERR_SAFETY_NOT_ATTESTED | 422 |
| ERR_OCCUPANCY_EXCEEDS_MAX | 422 |
| ERR_HOST_BARRED | 422 |
| ERR_PERMIT_CAP_REACHED | 422 |
| ERR_RENEWAL_WINDOW_CLOSED | 422 |
| ERR_NO_NIGHTS_TO_FILE | 422 |
| ERR_PERMIT_NOT_FILEABLE | 422 |
| ERR_PERMIT_NOT_ENFORCEABLE | 422 |
| ERR_FILING_HAS_REMITTANCES | 422 |
| ERR_DUPLICATE_FILING_PERIOD | 409 |
| ERR_PRIMARY_RESIDENCE_CONFLICT | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_DUPLICATE_ZONE_CODE | 409 |
| ERR_DUPLICATE_EMAIL | 409 |
| ERR_DUPLICATE_ADDRESS | 409 |
