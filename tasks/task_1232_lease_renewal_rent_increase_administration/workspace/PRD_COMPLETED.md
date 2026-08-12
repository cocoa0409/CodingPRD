# Lease Renewal Administration API — Product Requirements Document

## 1. Introduction

Multifamily revenue performance is decided in the ninety days before a lease expires. Price the renewal too aggressively and a good resident walks; price it too timidly and the portfolio leaves recoverable rent on the table. Miss a statutory notice deadline and the increase is unenforceable; let expirations bunch into the same calendar month and the property inherits a vacancy cliff. Operators today juggle these pressures with spreadsheets and calendar reminders, which is exactly where compliance errors and revenue leakage breed.

This document specifies the Lease Renewal Administration API, a system that runs the renewal cycle as a governed workflow rather than a pile of reminders. The platform codifies each jurisdiction's rent-control ordinance as data, prices every renewal offer through a configurable rate strategy that can never breach the statutory cap, selects lease terms that deliberately stagger expirations across the calendar, tracks resident responses through a bounded negotiation loop with tiered concession authority, supports non-renewal for cause with segregation of duties, and executes the final renewal through a two-signature document with a resident rescission window. Retention reporting closes the loop, telling ownership which expirations were kept, which were lost, and which are still in play.

A defining property of the system is that time itself is a governed input. All statutory deadlines, response windows, cure periods, and automatic conversions are evaluated against a logical clock that administrators advance explicitly, never against wall-clock time. Every rule in this document is stated against that logical clock.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or naming a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED`. Beyond authentication, each endpoint authorizes a fixed list of roles; a caller whose role is not on the list for the endpoint they invoked is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes five roles. `PlatformAdmin` is the platform operator, responsible for rent-cap policies, properties, units, resident onboarding, and the logical clock. `RegionalDirector` is the top staff tier with the widest concession-approval authority, inheriting every capability of the tiers below it. `PropertyManager` manages a property's day-to-day renewal program: serving and rescinding non-renewal notices, countersigning renewal documents, and all leasing-agent capabilities. `LeasingAgent` creates and negotiates renewal offers, submits concession requests, and drafts non-renewal notices. `Resident` is the leaseholding resident, acting only on resources anchored to their own lease.

The `X-User-ID` header binds to resources differently per role. When `X-User-Role` is `Resident`, `X-User-ID` is the `id` of the acting `Resident` record; ownership checks on any resource that chains to a `Lease` — an offer through its lease, a renewal document through its lease, or the lease itself — compare the lease's `resident_id` to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`. When `X-User-Role` is `PlatformAdmin`, `RegionalDirector`, `PropertyManager`, or `LeasingAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a workflow requires attribution (for example, as `issued_by_user_id` on an offer or `decided_by_user_id` on a concession decision) but never compares it against any entity's `id`.

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

Requests that match no route return the same error envelope with `error_id` `ERR_NOT_FOUND` (404); a known path invoked with an unsupported method returns `ERR_METHOD_NOT_ALLOWED` (405); an unexpected server-side failure returns `ERR_INTERNAL` (500).

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0. A non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`; out-of-range integers are clamped to the nearest bound — a `limit` below 1 becomes 1 and above 100 becomes 100, and a negative `offset` becomes 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order. The `meta` object of every list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`; `total_count` is the number of resources matching the endpoint's filters before pagination, and `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. The Logical Clock and the Scheduled Sweep

The system maintains a logical clock that governs every temporal rule in this document; it never consults wall-clock time. Before any administrative action advances it, the logical clock reads exactly `2026-05-01T00:00:00Z`. A `PlatformAdmin`-only capability advances the clock to a supplied `to_iso8601` instant and responds with the resulting `current_utc` plus a `transitions_applied` count. The supplied instant is normalized to UTC at whole-second precision and stored as given — no monotonicity check rejects a backward move — and every sweep comparison operates on the UTC calendar date of the clock, so time-of-day never influences which transitions fire. The `transitions_applied` count tallies every entity the sweep mutated — each notice, lease, offer, concession approval, or document changed — not merely each transition rule that fired.

Advancing the clock is never a passive read of time. Each advance synchronously applies every time-based transition that has fallen due, in one fixed sweep order: first, any served non-renewal notice whose cure window has lapsed is confirmed; second, any confirmed notice whose effective date has arrived is enforced; third, open offers are expired or voided — offers in `ISSUED` or `COUNTERED` past their `response_deadline_date` expire, and offers in `ACCEPTED` past their `execution_deadline_date` are voided; fourth and last, leases whose term end has been reached convert to month-to-month. The order matters operationally: a notice is always enforced before the sweep considers expiring offers or converting leases on the same date. Every entity mutated by the sweep has its `version` incremented and its `updated_at` refreshed. Offers still in `DRAFT` are never auto-expired by the sweep; they remain `DRAFT` until issued, withdrawn, or superseded, and an issue attempt that arrives after the statutory window has closed is rejected outright rather than silently expiring.

### 2.5. Common Resource Properties

All nine primary resources — rent-cap policies, properties, units, residents, leases, renewal offers, concession approvals, non-renewal notices, and renewal documents — share one set of system-managed fields. The `id` is a server-minted unique identifier formatted as a bare UUID, with no type prefix. The `created_at` timestamp records creation as an ISO 8601 UTC instant with three fractional digits. The `updated_at` timestamp follows the same format and refreshes on every modification. The `version` is an integer that starts at 1 when the resource is created and increments by one with every mutation of the resource, whether the mutation came from a client request or from a system-side cascade or clock sweep; any successful update call refreshes `updated_at` and increments `version` even when it changes no field value. Record timestamps — and the envelope's `api_request_timestamp` — read the server's wall clock; the logical clock of §2.4 governs only domain dates and deadlines, never record or envelope metadata.

Two date conventions run throughout the API. Fields named as dates (such as `term_start_date` or `effective_date`) are ISO calendar dates in `YYYY-MM-DD` form, while fields named as instants (such as `created_at`) are ISO 8601 UTC datetimes. Calendar-month arithmetic in this domain always preserves the day of month, clamping to the length of the target month when necessary. Date parsing on input accepts any three dash-separated numerals that form a valid calendar date — zero-padding of month and day is not enforced — while all stored and emitted dates are zero-padded `YYYY-MM-DD`.

### 2.6. Money, Basis Points, and Rounding Discipline

All rents are represented as integer cents — `monthly_rent_cents`, `current_market_rent_cents`, `proposed_rent_cents`, and their siblings — never as floating-point amounts. All rates, caps, increases, and premiums are represented as integer basis points, where ten thousand basis points equal one hundred percent.

Every calculation step that produces a stored value rounds half-up to a whole unit: basis-point intermediates round to a whole basis point, and rent results round to a whole cent. Multi-step calculations apply rounding at each pinned step in the prescribed order rather than once at the end. Where two evaluation orders could legitimately disagree by a cent, this document pins the order explicitly and names the forbidden shortcut.

### 2.7. Optimistic Concurrency Control

Two write operations guard their parent aggregate with optimistic concurrency control, because each legitimately destroys or repurposes state that a stale client could not have observed.

Creating a renewal offer against a lease requires the request to carry `expected_lease_version`, holding the lease `version` the client last read. Offer creation supersedes any open offer on the lease, so a writer holding a stale version would wipe out offers it never saw; when the supplied value does not match the lease's current `version`, the creation is rejected with `ERR_STALE_LEASE_VERSION` (HTTP 412), and the client must re-read the lease before resubmitting. An absent or non-integer `expected_lease_version` instead fails schema validation with `ERR_INVALID_REQUEST`.

Updating a property's name or staggering band accepts an optional `expected_property_version` under the same rule: when the field is supplied it must be an integer equal to the property's current `version` — a non-integer value fails with `ERR_INVALID_REQUEST`, a mismatch with `ERR_STALE_PROPERTY_VERSION` (HTTP 412) — and when the field is omitted the update proceeds with no OCC check at all. No other endpoint accepts a version field; all other mutations proceed without an OCC check.

### 2.8. Statutory Rent-Cap and Notice Primitives

Every property operates under exactly one rent-cap policy, which encodes its jurisdiction's ordinance as numbers. The policy's governing ceiling — its `effective_cap_bps` — is derived, never entered directly: it is the lesser of the base cap plus the CPI pass-through on one side and the absolute statutory hard ceiling on the other. This derivation runs at policy creation and again on every policy update, so the stored value always reflects the current components.

Three consumption rules keep policy edits honest across the renewal lifecycle. An offer being created snapshots the policy's effective cap onto itself, and that snapshot governs the provisional pricing shown to the resident no matter how the policy later drifts. A revision issued mid-negotiation is checked against the policy's *current* effective cap, not the snapshot — the statute binds the offer at the moment it is re-issued. Final execution at document countersign prices the renewal against the then-current policy and then-current market rent once more. Updating a policy therefore never rewrites history on open offers, yet always binds the next forward-looking act.

Notice periods are tiered by the size of the proposed increase. Each policy declares a threshold in basis points and two notice periods: a short period for modest increases and a long period for increases above the threshold. The comparison is strict — an increase exactly equal to the threshold takes the short period.

### 2.9. Validation Pipeline and Error Precedence

Every request passes through a fixed validation pipeline, and the first failing stage wins: the response reports exactly one error, drawn from the earliest stage that fails. The stages run in this order.

1. **Authentication.** `X-User-ID` and `X-User-Role` must be present, and the role must be one of the five declared roles. Failures return `ERR_UNAUTHENTICATED`.
2. **Role authorization.** The caller's role must appear in the invoked endpoint's authorized list, else `ERR_FORBIDDEN_ROLE`.
3. **Request schema.** Required fields must be present, types correct, enum members valid, dates well-formed `YYYY-MM-DD`, and integer ranges honored — for example `term_months` must be at least 1, a property's `min_term_months` must not exceed its `max_term_months`, a resident response's `response_type` must be one of `ACCEPT`, `DECLINE`, or `COUNTER`, a `COUNTER` response must carry a `counter_rent_cents` greater than zero, and a notice citing `LEASE_VIOLATION` must carry an `evidence_ref`. Any failure returns `ERR_INVALID_REQUEST`.
4. **Existence.** Path resource identifiers are validated left to right — the request is rejected with the not-found error of the first missing identifier — and then body foreign keys (`unit_id`, `resident_id`, `rent_cap_policy_id`) are validated. The nine errors are `ERR_POLICY_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_CONCESSION_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, and `ERR_DOCUMENT_NOT_FOUND`.
5. **Ownership.** A `Resident` caller must own the lease anchoring the target resource chain — offer to lease, document to lease, or the lease itself — else `ERR_NOT_RESOURCE_OWNER`. This stage governs responding to an offer, signing a renewal document, rescinding an executed renewal, and every Resident-role read.
6. **Optimistic concurrency.** Where an endpoint takes an expected-version field (per §2.7), the supplied value must match the parent's current `version`, else `ERR_STALE_LEASE_VERSION` or `ERR_STALE_PROPERTY_VERSION`.
7. **State preconditions.** The target entity must be in a state that permits the transition, else the matching state error: `ERR_LEASE_NOT_ISSUABLE`, `ERR_OFFER_NOT_DRAFT`, `ERR_OFFER_NOT_ISSUED`, `ERR_OFFER_NOT_COUNTERED`, `ERR_OFFER_NOT_WITHDRAWABLE`, `ERR_DOCUMENT_INVALID_STATE`, `ERR_NOTICE_NOT_DRAFT`, `ERR_NOTICE_NOT_SERVED`, or `ERR_CONCESSION_NOT_SUBMITTED`.
8. **Statutory rent cap.** A revised offer's recomputed increase must fit under the policy's current effective cap, else `ERR_RENT_CAP_EXCEEDED`.
9. **Statutory temporal windows.** Issue and high-tier revise must land inside the statutory notice window (`ERR_NOTICE_WINDOW_MISSED`); serving a notice must leave the statutory lead time (`ERR_INSUFFICIENT_NOTICE_LEAD`) and target a valid end date (`ERR_INVALID_EFFECTIVE_DATE`); rescission of an executed renewal must land inside its short window (`ERR_RESCISSION_WINDOW_LAPSED`). The first three of these are 422-class business violations, while `ERR_RESCISSION_WINDOW_LAPSED` is a 409 state-and-time hybrid.
10. **Domain constraints**, evaluated in this fixed sub-order: (a) a countered or revised term must sit inside the property's staggering band (`ERR_TERM_OUTSIDE_STAGGERING_BAND`); (b) a new lease must not overlap another live lease on the same unit (`ERR_LEASE_TERM_OVERLAP`); (c) jurisdiction codes and per-property unit numbers must be unique (`ERR_DUPLICATE_JURISDICTION`, `ERR_DUPLICATE_UNIT_NUMBER`); (d) the negotiation round cap (`ERR_MAX_NEGOTIATION_ROUNDS`); (e) segregation of duties (`ERR_SEGREGATION_OF_DUTIES`); (f) concession approver tier (`ERR_CONCESSION_TIER_EXCEEDED`); (g) the repositioning quarterly quota (`ERR_REPOSITIONING_QUOTA_EXCEEDED`); (h) the approved-concession gate on below-strategy revisions (`ERR_CONCESSION_APPROVAL_REQUIRED`). HTTP statuses inside this stage vary by error: `ERR_TERM_OUTSIDE_STAGGERING_BAND` and `ERR_REPOSITIONING_QUOTA_EXCEEDED` are 422; `ERR_SEGREGATION_OF_DUTIES` and `ERR_CONCESSION_TIER_EXCEEDED` are 403; the remainder are 409.
11. **Concession magnitude.** A concession request whose implied discount exceeds the absolute ceiling is refused at submission with `ERR_CONCESSION_EXCEEDS_ABSOLUTE_MAX`.

### 2.10. Cross-Entity Cascades and Snapshot Restoration

Renewal administration is a web of linked records, and several single acts fan out into multi-entity mutations. Three cascades recur throughout §3 and are collected here as system-wide commitments.

First, any event that removes the last open offer from a lease in `RENEWAL_PENDING` — whether the offer was declined, expired, withdrawn, or superseded — reverts the lease to the status it held when the offer cycle began, recorded on the lease as `status_before_offer`, and clears that field. Wherever this document speaks of an open offer without naming a narrower set — this revert check included — an offer counts as open in `DRAFT`, `ISSUED`, `COUNTERED`, or `ACCEPTED`; the supersede cascade of §3.3 and the offer withdrawals of §3.4 and §3.6 name their narrower sets explicitly. Second, withdrawing or superseding an offer — including the mass withdrawal triggered when a non-renewal notice is served — voids every still-pending concession approval attached to that offer; approvals already consumed into a revision are unaffected. Third, the destructive acts in the domain are always compensated by snapshots: serving a notice captures the lease's prior status on the notice so rescission can restore it verbatim, and countersigning a renewal document captures the lease's full economic state on the document so a resident rescission can restore it exactly. Withdrawn offers are the one thing restoration never resurrects: a rescinded notice returns the lease to its former status, but the offers that were withdrawn at serve time stay withdrawn.

## 3. Business Logic & Workflows

### 3.1. Portfolio Foundations: Jurisdictions, Properties, and Units

Before any lease can be renewed, a `PlatformAdmin` builds the portfolio's foundation. Each jurisdiction's rent-control ordinance becomes a **RentCapPolicy** carrying a unique `jurisdiction_code` — a duplicate submission is rejected with `ERR_DUPLICATE_JURISDICTION` — along with the `base_cap_bps` and `cpi_adjustment_bps` components (both non-negative integer basis points), the absolute `hard_ceiling_bps`, the `high_increase_threshold_bps` at which the long notice period engages, the two notice tiers `notice_days_low` and `notice_days_high`, and the `non_renewal_notice_days` lead time required when ending a tenancy. The derived `effective_cap_bps` follows §2.8. A policy can be updated later — typically for an annual CPI adjustment — by supplying any subset of the seven numeric fields, each of which must be an integer; the update recomputes the effective cap and bumps the policy's `version`, and the creation-time non-negativity rules are not re-enforced on update; per §2.8, existing offers keep their frozen cap snapshots while future revisions and executions bind to the updated policy.

A **Property** is then registered with a display `name`, the `rent_cap_policy_id` of its governing policy (an unknown policy id is rejected with `ERR_POLICY_NOT_FOUND`), and a staggering band defined by `min_term_months` and `max_term_months`. The band bounds every lease term the property will ever offer: the minimum must be at least 1, the maximum must be at least the minimum, and violations of either surface as `ERR_INVALID_REQUEST`. Updating a property's name or band is an OCC-guarded write per §2.7, taking an optional `expected_property_version`. Properties may be listed with an optional `rent_cap_policy_id` filter.

Each rentable **Unit** is created under a property via `property_id` (an unknown property id yields `ERR_PROPERTY_NOT_FOUND`) with a `unit_number` unique within that property — a collision is rejected with `ERR_DUPLICATE_UNIT_NUMBER` — a non-negative `bedrooms` count, and the unit's `current_market_rent_cents` (a non-negative integer), which feeds the pricing gap calculation in §3.3. Units may be listed filtered by `property_id`.

Residents complete the foundation. A **Resident** is onboarded with a `full_name` and `email` by a `PlatformAdmin`, `PropertyManager`, or `LeasingAgent`; the resulting record's `id` becomes the ownership anchor for every Resident-role act described later.

### 3.2. Lease Onboarding, Term Geometry, and Month-to-Month Conversion

A `PlatformAdmin` or `PropertyManager` creates a **Lease** by supplying the `unit_id`, the primary `resident_id`, a `term_start_date`, a `term_months` length of at least one whole month, and the agreed `monthly_rent_cents`, a non-negative integer. Unknown unit or resident ids are rejected with `ERR_UNIT_NOT_FOUND` and `ERR_RESIDENT_NOT_FOUND` respectively. At creation the system derives the lease's `term_end_date` by adding `term_months` calendar months to the start date — preserving the day of month and clamping to month length — and treats the occupancy as the half-open interval that includes the start date and excludes the end date. The lease's `property_id` is denormalized from its unit at creation so that property-scoped queries and calculations never chase the join. A new lease is rejected with `ERR_LEASE_TERM_OVERLAP` when its half-open interval would intersect the interval of any other non-`ENDED` lease on the same unit. A lease is born in `ACTIVE` status; `ENDED` is its terminal status.

Leases may be listed with `unit_id`, `property_id`, `resident_id`, or `status` filters, and individual leases are readable by all staff roles and — scoped to their own tenancy — by residents; a `Resident` caller's lease list is implicitly restricted to leases anchored to that resident's own record before any query filters apply.

When the logical clock's sweep finds a lease in `ACTIVE` or `RENEWAL_PENDING` whose `term_end_date` has been reached or passed, the lease converts to month-to-month: its status becomes `MTM`, `mtm_converted_on` records the clock date, and its rent is reset by the month-to-month premium calculation. The premium base is the `proposed_rent_cents` of the most recently created offer for the lease that was actually issued (an offer whose `issued_on_date` is set, breaking ties by latest creation); if no issued offer exists, the base is the lease's `monthly_rent_cents` grown by the policy's `effective_cap_bps` and rounded half-up to whole cents. The conversion rent is then the base grown by a premium of 1,500 basis points — fifteen percent — rounded half-up to whole cents. The rounding order is pinned: the base is rounded to whole cents first, the premium is applied to that rounded base, and the result is rounded again. Growing the rent by cap and premium in a single expression with one final rounding is a forbidden shortcut, because it can differ from the pinned order by a cent. If an offer cycle is still open when the conversion fires, the lease's `status_before_offer` is set to `MTM` so a later collapse of the cycle reverts to the right status; otherwise the field stays null.

### 3.3. Renewal Offer Generation: Pricing, Term Staggering, and Statutory Notice Windows

A `LeasingAgent`, `PropertyManager`, or `RegionalDirector` opens a renewal cycle by creating a **RenewalOffer** against a lease identified in the request path as `leaseId`. This is the OCC-guarded write of §2.7: the request must carry `expected_lease_version` matching the lease's current `version`, or it is rejected with `ERR_STALE_LEASE_VERSION`. The request may optionally name a `rate_strategy` — `AGGRESSIVE`, `BALANCED`, or `CONSERVATIVE` — which defaults to `BALANCED` when omitted. The lease must be in `ACTIVE`, `MTM`, or `RENEWAL_PENDING` for the cycle to open; creating an offer against an `ENDED` or `NON_RENEWAL_NOTICED` lease is rejected with `ERR_LEASE_NOT_ISSUABLE`.

Creation computes the entire pricing envelope. The lease's current `monthly_rent_cents` is captured as the offer's `base_rent_cents`, the policy's current `effective_cap_bps` is frozen onto the offer as `cap_bps_snapshot`, and `offer_round` starts at 1. The provisional `proposed_rent_cents` then comes out of a six-step pipeline. First, the market gap: the amount by which the unit's `current_market_rent_cents` exceeds the lease's `monthly_rent_cents`, divided by the lease's `monthly_rent_cents` and expressed in basis points, rounded half-up to a whole basis point, and never below zero — and defined as zero basis points outright when the lease's `monthly_rent_cents` is zero. Second, the strategy share: `AGGRESSIVE` captures one hundred percent of the gap, `BALANCED` sixty percent, and `CONSERVATIVE` thirty percent, with the product rounded half-up to a whole basis point. Third, a term discount rewards longer commitments: ten basis points for every month of `offered_term_months` beyond twelve, capped at one hundred eighty basis points and never below zero. Fourth, the discounted increase is the strategy share minus the term discount, never below zero. Fifth, the increase is capped at the applicable cap in basis points — for this provisional variant, the frozen `cap_bps_snapshot`. Sixth, the proposed rent is the lease's `monthly_rent_cents` grown by the capped increase, rounded half-up to whole cents. The offer's `proposed_increase_bps` records the increase of `proposed_rent_cents` over `base_rent_cents` in basis points, recomputed from the rounded proposed rent, rounded half-up to a whole basis point, never below zero, and defined as zero when the base rent is zero.

The offered term itself is machine-chosen to smooth the property's expiration calendar. Every integer term from the property's `min_term_months` to its `max_term_months` is a candidate. For each candidate, the system projects the resulting end date by adding that many calendar months to a base — the lease's own `term_end_date`, or the current clock date when the lease is already `MTM`. The load on a candidate is the count of the property's other leases in `ACTIVE`, `RENEWAL_PENDING`, or `NON_RENEWAL_NOTICED` status whose `term_end_date` falls in the calendar month containing the projected end, plus the count of the property's open offers — those in `DRAFT`, `ISSUED`, `COUNTERED`, or `ACCEPTED` — whose own projected end falls in that same month. The subject lease and its own offers never contribute to the load. The candidate with the smallest load wins, and ties break in favor of the longer term. Because the band is validated non-empty at property write time, a candidate always exists; the winner is stored as `offered_term_months`.

Statutory notice fields complete the offer. When `proposed_increase_bps` is strictly greater than the policy's `high_increase_threshold_bps`, `notice_days_required` takes the long period `notice_days_high`; an increase equal to or below the threshold takes `notice_days_low`. The `latest_issue_date` is then the lease's `term_end_date` minus the required notice days — or null when the lease is `MTM`, where no fixed term end exists and no statutory issue window applies. Offers begin life in `DRAFT` with `issued_on_date`, `issued_by_user_id`, `response_deadline_date`, `accepted_on_date`, `execution_deadline_date`, `executed_rent_cents`, `counter_rent_cents`, and `counter_term_months` all null.

Creating an offer is deliberately destructive to its predecessors: any still-open sibling offers for the same lease — those in `DRAFT`, `ISSUED`, or `COUNTERED` — are immediately moved to `SUPERSEDED`, their pending concession approvals are voided per §2.10, and the new offer's `supersedes_offer_id` records the most recently created of the superseded offers (null when none existed). The lease's `version` increments by one as part of the creation. Offers may be listed with `lease_id`, `status`, or `supersedes_offer_id` filters; a `Resident` caller's list is implicitly restricted to offers anchored to that resident's own lease.

### 3.4. Issuance, Resident Response, and the Negotiation Loop

A staff member — `LeasingAgent`, `PropertyManager`, or `RegionalDirector` — issues a `DRAFT` offer to the resident; issuing an offer in any other state is rejected with `ERR_OFFER_NOT_DRAFT`. Two guards bind the act. The lease must be in `ACTIVE`, `MTM`, or `RENEWAL_PENDING` — an `ENDED` or `NON_RENEWAL_NOTICED` lease yields `ERR_LEASE_NOT_ISSUABLE`. And the statutory window must still be open: for a fixed-term lease the clock date must be on or before the offer's `latest_issue_date`, while for an `MTM` lease the null `latest_issue_date` means no window applies; a late issue is rejected with `ERR_NOTICE_WINDOW_MISSED`. These checks fire in the order stated: the offer's `DRAFT` state first, then the lease's issuable state, then the statutory window. A successful issue stamps `issued_on_date` with the clock date and `issued_by_user_id` with the acting operator, sets the `response_deadline_date` to the earlier of fourteen days from the clock date and the lease's `term_end_date` (for an `MTM` lease, simply fourteen days out), and moves the offer to `ISSUED`. Issuing also moves the lease from `ACTIVE` or `MTM` into `RENEWAL_PENDING`, capturing the prior status in `status_before_offer` on this first entry into the cycle.

The resident answers an `ISSUED` offer — and only an `ISSUED` one, else `ERR_OFFER_NOT_ISSUED` — by submitting a `response_type` of `ACCEPT`, `DECLINE`, or `COUNTER`. Ownership per §2.1 is enforced with `ERR_NOT_RESOURCE_OWNER`. Acceptance stamps `accepted_on_date` with the clock date, sets the `execution_deadline_date` ten days out, moves the offer to `ACCEPTED`, and automatically generates the renewal document described in §3.7 — at most one document ever exists per offer. Declining moves the offer to `DECLINED` and triggers the lease revert check of §2.10: if no other offer remains open for the lease, a lease sitting in `RENEWAL_PENDING` returns to the status captured in `status_before_offer` (`ACTIVE` or `MTM`) and the field clears.

A `COUNTER` response keeps the negotiation alive. It must carry a `counter_rent_cents` greater than zero and may carry an optional `counter_term_months`; a countered term outside the property's staggering band is rejected with `ERR_TERM_OUTSIDE_STAGGERING_BAND`. Negotiation is bounded at three rounds: when the offer's `offer_round` has already reached 3, a further counter is rejected with `ERR_MAX_NEGOTIATION_ROUNDS`. A successful counter records `counter_rent_cents` and — only when one was supplied — `counter_term_months`, which stays null otherwise, and moves the offer to `COUNTERED`.

Staff close a counter by issuing a revised round on the `COUNTERED` offer — revising an offer in any other state returns `ERR_OFFER_NOT_COUNTERED`. The revision takes optional `revised_rent_cents` and `revised_term_months`: the rent defaults to the resident's `counter_rent_cents` and the term defaults to the current `offered_term_months` when omitted. Four gates then apply. The revised term must sit inside the staggering band (`ERR_TERM_OUTSIDE_STAGGERING_BAND`). If the revised rent is below the current `proposed_rent_cents`, an `APPROVED` concession approval for this offer whose `requested_rent_cents` exactly equals the revised rent must already exist, else `ERR_CONCESSION_APPROVAL_REQUIRED`. The recomputed increase over `base_rent_cents` must fit within the policy's *current* `effective_cap_bps`, else `ERR_RENT_CAP_EXCEEDED`. And when the recomputed increase crosses into the high-notice tier, the clock date must be no later than the lease's `term_end_date` minus `notice_days_high`, else `ERR_NOTICE_WINDOW_MISSED`; an `MTM` lease is exempt from this high-tier window check, no fixed term end governing it. A successful revise increments `offer_round` by one, overwrites `proposed_rent_cents` with the revised rent, recomputes `proposed_increase_bps`, `notice_days_required`, and `latest_issue_date`, adopts the revised term as `offered_term_months`, restamps `issued_on_date` with the clock date (while `issued_by_user_id` keeps its original value), resets the `response_deadline_date` to the earlier of fourteen days out and the term end, returns the offer to `ISSUED`, and marks the consumed concession approval `APPLIED`.

Any open offer in `DRAFT`, `ISSUED`, or `COUNTERED` may be withdrawn by staff; offers already in a terminal state reject the withdrawal with `ERR_OFFER_NOT_WITHDRAWABLE`. Withdrawal moves the offer to `WITHDRAWN`, voids its pending concession approvals, and runs the lease revert check. Two terminal outcomes belong to the clock sweep instead: an offer in `ISSUED` or `COUNTERED` whose `response_deadline_date` has passed becomes `EXPIRED`, and an offer in `ACCEPTED` whose `execution_deadline_date` has passed becomes `VOIDED` — which also voids its renewal document if that document is still unsigned or resident-signed. Both sweep outcomes void pending concessions and run the lease revert check.

### 3.5. Concession Authority: Submission, Tiered Approval, and Consumption

Negotiation sometimes calls for a rent below what the rate strategy proposed, and the system treats that discount as a governed act of retention spending. A staff member requests the authority by creating a **ConcessionApproval** against an offer identified in the path as `offerId`, supplying the `requested_rent_cents` they want permission to offer — a positive integer — and an optional `reason`. The offer must be `COUNTERED` — submitting against an offer in any other state returns `ERR_OFFER_NOT_COUNTERED`. At submission the system computes `concession_bps`: the difference between the offer's current `proposed_rent_cents` and the `requested_rent_cents`, divided by the `proposed_rent_cents`, expressed in basis points and rounded half-up. A request whose implied discount exceeds the absolute ceiling of 2,000 basis points is refused on the spot with `ERR_CONCESSION_EXCEEDS_ABSOLUTE_MAX`. The submitter is recorded as `requested_by_user_id`, `decided_by_user_id` stays null, and the request enters `SUBMITTED`.

Approval authority is tiered by role, with each tier's limit an inclusive upper bound on `concession_bps`: a `LeasingAgent` may approve up to 300 basis points, a `PropertyManager` up to 800, and a `RegionalDirector` up to the absolute ceiling of 2,000. An approver whose tier does not cover the requested discount is rejected with `ERR_CONCESSION_TIER_EXCEEDED`. Two further checks bind every decision: the linked offer must still be `COUNTERED` for an approval (`ERR_OFFER_NOT_COUNTERED` otherwise), and segregation of duties forbids the requester from deciding their own request — an approver or denier whose identity matches `requested_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`. Deciding a request that has left `SUBMITTED` returns `ERR_CONCESSION_NOT_SUBMITTED`; within the state-precondition stage, that `SUBMITTED` check fires before the linked-offer `COUNTERED` check. A successful decision records `decided_by_user_id` and moves the request to `APPROVED` or `DENIED`.

An `APPROVED` approval has exactly one use. When a revision priced at its `requested_rent_cents` is issued per §3.4, the approval is consumed into `APPLIED`. Approvals still pending — `SUBMITTED` or `APPROVED` — are voided whenever their offer is withdrawn, superseded, or expired, or when the lease itself is ended. Concession approvals may be listed with `offer_id` or `status` filters.

### 3.6. Non-Renewal for Cause: Notices, Cure, and Enforcement

Not every tenancy should be renewed. A staff member drafts a **NonRenewalNotice** against a lease identified as `leaseId`, naming a `cause_type` of `LEASE_VIOLATION`, `REPEATED_LATE_PAYMENT`, `PROPERTY_REPOSITIONING`, or `OWNER_OCCUPANCY`, plus the `effective_date` on which the tenancy should end. A `LEASE_VIOLATION` notice must cite an `evidence_ref` (its absence is an `ERR_INVALID_REQUEST`); for the other causes the reference is optional. The creator is recorded as `created_by_user_id`, and the notice waits in `DRAFT` with `served_on_date`, `cure_deadline_date`, `prior_lease_status`, and `served_by_user_id` all null. Notices may be listed with `lease_id` or `status` filters.

Serving the notice is restricted to `PropertyManager` and `RegionalDirector` and is guarded by five checks. The server must differ from the creator (`ERR_SEGREGATION_OF_DUTIES`). The notice must still be `DRAFT` (`ERR_NOTICE_NOT_DRAFT`). The lease must be in `ACTIVE`, `MTM`, or `RENEWAL_PENDING` (`ERR_LEASE_NOT_ISSUABLE`). The `effective_date` must fall on or after the lease's `term_end_date` (`ERR_INVALID_EFFECTIVE_DATE`), and the clock date must be no later than the `effective_date` minus the policy's `non_renewal_notice_days`, preserving the statutory lead time (`ERR_INSUFFICIENT_NOTICE_LEAD`); when both temporal checks would fail, the effective-date check fires first. Finally, property repositioning is quota-limited: serving a `PROPERTY_REPOSITIONING` notice is rejected with `ERR_REPOSITIONING_QUOTA_EXCEEDED` when two or more other notices with that cause, in `SERVED`, `CONFIRMED`, or `ENFORCED` status, already exist on the same property with an `effective_date` in the same calendar quarter.

Serving is the deepest cascade in the system, and it fans out in three links. At the first link, the notice itself is stamped — `served_on_date` takes the clock date, `cure_deadline_date` is set ten days out, `served_by_user_id` records the server — and the lease moves to `NON_RENEWAL_NOTICED` with its current status captured into the notice's `prior_lease_status`. At the second link, the lease leaving an issuable status withdraws its open offers: every `DRAFT`, `ISSUED`, or `COUNTERED` offer for the lease moves to `WITHDRAWN`, while an `ACCEPTED` offer survives until its own execution deadline. At the third link, each withdrawn offer voids its pending concession approvals per §2.10 — an effect of the withdrawals, not of the serve directly.

A resident who cures the cause in time can be reprieved: within the cure window, a `PropertyManager` or `RegionalDirector` rescinds the `SERVED` notice, moving it to `RESCINDED` and restoring the lease's status verbatim from `prior_lease_status` — `ACTIVE`, `MTM`, or `RENEWAL_PENDING` exactly as captured. The offers withdrawn at serve time are not resurrected. Once the cure window lapses the rescue is gone: the clock sweep moves the notice from `SERVED` to `CONFIRMED` when the clock passes `cure_deadline_date`, and a rescind attempt against a notice that is no longer `SERVED` returns `ERR_NOTICE_NOT_SERVED` — as does a rescind attempt against a still-`SERVED` notice whose `cure_deadline_date` the clock has already passed but the sweep has not yet confirmed. Neither serving nor rescinding a notice touches the lease's `status_before_offer`; rescission restores only the lease's `status` from `prior_lease_status`.

Enforcement is the clock's final word. When the sweep finds a `CONFIRMED` notice whose `effective_date` has arrived, the notice moves to `ENFORCED`, the lease moves to `ENDED` with `status_before_offer` cleared, any `ACCEPTED` offer still waiting on execution is moved to `VOIDED`, and that offer's renewal document — if still `GENERATED` or `RESIDENT_SIGNED` — is voided with it. No offer can legitimately still be open at enforcement: non-accepted offers were withdrawn at serve, and an accepted offer's ten-day execution deadline always lapses before any statutorily valid effective date.

### 3.7. Renewal Document Execution and Rescission

Resident acceptance of an offer automatically creates the **RenewalDocument** for that offer in `GENERATED` status, denormalizing the `lease_id` from the offer; each offer has at most one document. The document tracks `executed_rent_cents`, `countersigned_on_date`, and `rescind_deadline_date`, all null until countersign, plus a snapshot block — `prior_lease_status`, `prior_monthly_rent_cents`, `prior_term_start_date`, `prior_term_end_date`, and `prior_term_months` — that also stays null until countersign. Documents may be listed with `offer_id`, `lease_id`, or `status` filters; a `Resident` caller's list is implicitly restricted to documents anchored to that resident's own lease.

Execution is a two-signature ceremony. The resident signs first: signing requires the document to be `GENERATED` (anything else returns `ERR_DOCUMENT_INVALID_STATE`) and enforces resident ownership per §2.1, moving the document to `RESIDENT_SIGNED`. A `PropertyManager` or `RegionalDirector` then countersigns, which requires `RESIDENT_SIGNED` (`ERR_DOCUMENT_INVALID_STATE` otherwise) and requires the lease not to be `ENDED` — unreachable in practice, since lease enforcement voids the document first, but enforced as defense in depth and likewise answered with `ERR_DOCUMENT_INVALID_STATE`, the `RESIDENT_SIGNED` check firing first. Countersign is the moment the renewal's economics are locked by the final pricing variant: the six-step pipeline of §3.3 runs again with the policy's *then-current* `effective_cap_bps`, the unit's *then-current* `current_market_rent_cents`, and the lease's *then-current* `monthly_rent_cents` as the base, while the offer's `rate_strategy` and `offered_term_months` carry through unchanged. The result is stored as `executed_rent_cents` on both the document and the offer, and will differ from the provisional `proposed_rent_cents` whenever policy or market conditions drifted between issue and execution.

Countersign then rewrites three records in one act. The document captures its snapshot: the lease's current `monthly_rent_cents`, `term_start_date`, `term_months`, and `term_end_date` are copied into the four `prior_*` fields, and `prior_lease_status` takes the lease's `status_before_offer` when set, else the lease's current status; `countersigned_on_date` takes the clock date and `rescind_deadline_date` is set three days out. The offer moves from `ACCEPTED` to `EXECUTED`. The lease is renewed: its `monthly_rent_cents` becomes the executed rent, its new `term_start_date` is the later of the old `term_end_date` and the current clock date, `term_months` becomes the offer's `offered_term_months`, `term_end_date` is recomputed from those values, status returns to `ACTIVE`, `status_before_offer` clears, and the lease's `version` increments by one.

The resident holds a short cooling-off right. Within three days of countersign — the clock date must be on or before `rescind_deadline_date`, else `ERR_RESCISSION_WINDOW_LAPSED` — the resident may rescind the executed renewal, which requires the document to be `COUNTERSIGNED` (`ERR_DOCUMENT_INVALID_STATE` otherwise) and enforces resident ownership. Rescission moves the document to `RESCINDED`, moves the offer from `EXECUTED` to `VOIDED`, and restores the lease from the document's snapshot: the four economic fields return to their `prior_*` values, status becomes the captured `prior_lease_status`, and `status_before_offer` clears. Separately, a document that never reaches countersign is voided whenever its offer is voided — whether by a lapsed execution deadline or by lease enforcement.

### 3.8. Retention Measurement and Expiration Forecasting

Ownership reads the program's results through two property-scoped reports. The retention report takes a `cohort_start` and `cohort_end` bounding an inclusive window plus a `variant` selector, and is available to `PlatformAdmin`, `RegionalDirector`, and `PropertyManager`; a missing parameter, a malformed cohort date, or a `variant` other than `TRAILING` or `PIPELINE` is rejected with `ERR_INVALID_REQUEST`. The cohort gathers every lease of the property whose `term_end_date` falls inside the window, plus every lease holding a renewal document that reached `COUNTERSIGNED` — whether the document is currently `COUNTERSIGNED` or was later `RESCINDED` — whose `prior_term_end_date` falls inside the window; an executed renewal moves the lease's own term end out of the window, so the document's captured prior end is what anchors the lease to its original cohort. A lease never appears twice in the same window.

What counts as retained depends on the variant. Under `TRAILING`, retained means a cohort lease holding a renewal document that is currently `COUNTERSIGNED` with its `prior_term_end_date` in the window; a document since rescinded does not count, because the renewal was undone. Under `PIPELINE`, retained additionally includes cohort leases with an offer currently `ACCEPTED` but not yet executed, and cohort leases currently in `MTM` — so the pipeline figure is always at least the trailing figure for the same cohort. The report returns `cohort_size`, `retained_count`, `mtm_count` (cohort leases currently in `MTM`), `lost_count` (leases `ENDED` without an executed renewal — that is, with no renewal document currently `COUNTERSIGNED`), and `pending_count` (leases with an open offer not yet accepted), echoes the `variant`, and computes `retention_rate_bps` as the retained share of the cohort expressed in basis points and rounded half-up — null when the cohort is empty.

The expiration forecast supports the staggering algorithm's forward view and is available to all four staff roles. Given an optional `months_ahead` — defaulting to 12, clamped to the range 1 through 60, with a non-integer value rejected as `ERR_INVALID_REQUEST` — it walks each calendar month from the current clock month forward through the requested horizon and reports two counts per month: the committed expirations — leases in `ACTIVE`, `RENEWAL_PENDING`, or `NON_RENEWAL_NOTICED` whose `term_end_date` falls in that month — and the projected expirations — open offers in `DRAFT`, `ISSUED`, `COUNTERED`, or `ACCEPTED` whose projected end per §3.3 falls in that month. The response carries a `window_start` — the first day of the current clock month — and a `months` array ordered by month ascending, each entry carrying `month` (in `YYYY-MM` form), `committed`, and `projected`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including all state-transition actions — and all read operations return `200 OK`. Request and response payloads for each endpoint are governed by the workflows in §3 rather than restated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock; synchronously applies all due time-based transitions in fixed sweep order | PlatformAdmin |
| POST | `/rent-cap-policies` | Create a rent-cap policy for a jurisdiction | PlatformAdmin |
| GET | `/rent-cap-policies/{id}` | Get a rent-cap policy | PlatformAdmin, RegionalDirector, PropertyManager, LeasingAgent |
| PATCH | `/rent-cap-policies/{id}` | Update a rent-cap policy; recomputes the effective cap without altering existing offer snapshots | PlatformAdmin |
| POST | `/properties` | Create a property with its staggering band | PlatformAdmin |
| GET | `/properties` | List properties | PlatformAdmin, RegionalDirector, PropertyManager, LeasingAgent |
| GET | `/properties/{id}` | Get a property | PlatformAdmin, RegionalDirector, PropertyManager, LeasingAgent |
| PATCH | `/properties/{id}` | Update property name / staggering band; OCC via expected property version | PlatformAdmin |
| GET | `/properties/{id}/retention-metrics` | Retention report for the lease-expiry cohort in the inclusive window; variant selects TRAILING vs PIPELINE | PlatformAdmin, RegionalDirector, PropertyManager |
| GET | `/properties/{id}/expiration-forecast` | Per-month committed and projected lease-expiration counts used by staggering | PlatformAdmin, RegionalDirector, PropertyManager, LeasingAgent |
| POST | `/units` | Create a unit | PlatformAdmin |
| GET | `/units` | List units | PlatformAdmin, RegionalDirector, PropertyManager, LeasingAgent |
| GET | `/units/{id}` | Get a unit | PlatformAdmin, RegionalDirector, PropertyManager, LeasingAgent |
| POST | `/residents` | Onboard a resident | PlatformAdmin, PropertyManager, LeasingAgent |
| GET | `/residents` | List residents | PlatformAdmin, RegionalDirector, PropertyManager, LeasingAgent |
| GET | `/residents/{id}` | Get a resident | PlatformAdmin, RegionalDirector, PropertyManager, LeasingAgent |
| POST | `/leases` | Create a lease; half-open term overlap with another non-ENDED lease on the same unit is rejected | PlatformAdmin, PropertyManager |
| GET | `/leases` | List leases with filters | PlatformAdmin, RegionalDirector, PropertyManager, LeasingAgent, Resident |
| GET | `/leases/{id}` | Get a lease | PlatformAdmin, RegionalDirector, PropertyManager, LeasingAgent, Resident |
| POST | `/leases/{leaseId}/renewal-offers` | Create a renewal offer (DRAFT) with system-selected term and provisional pricing; supersedes open sibling offers; OCC via expected lease version | LeasingAgent, PropertyManager, RegionalDirector |
| GET | `/renewal-offers` | List renewal offers with filters | PlatformAdmin, RegionalDirector, PropertyManager, LeasingAgent, Resident |
| GET | `/renewal-offers/{id}` | Get a renewal offer | PlatformAdmin, RegionalDirector, PropertyManager, LeasingAgent, Resident |
| POST | `/renewal-offers/{id}/issue` | Issue a DRAFT offer to the resident; statutory notice window enforced | LeasingAgent, PropertyManager, RegionalDirector |
| POST | `/renewal-offers/{id}/respond` | Resident responds to an ISSUED offer: ACCEPT, DECLINE, or COUNTER | Resident |
| POST | `/renewal-offers/{id}/revise` | Issue a revised round on a COUNTERED offer; may consume an APPROVED concession | LeasingAgent, PropertyManager, RegionalDirector |
| POST | `/renewal-offers/{id}/withdraw` | Withdraw an open offer (DRAFT/ISSUED/COUNTERED) | LeasingAgent, PropertyManager, RegionalDirector |
| POST | `/renewal-offers/{offerId}/concession-approvals` | Request authority to offer rent below the strategy-proposed rent; requires offer COUNTERED | LeasingAgent, PropertyManager, RegionalDirector |
| GET | `/concession-approvals` | List concession approvals with filters | PlatformAdmin, RegionalDirector, PropertyManager, LeasingAgent |
| GET | `/concession-approvals/{id}` | Get a concession approval | PlatformAdmin, RegionalDirector, PropertyManager, LeasingAgent |
| POST | `/concession-approvals/{id}/approve` | Approve a SUBMITTED concession within the approver's authority tier; approver must differ from requester | LeasingAgent, PropertyManager, RegionalDirector |
| POST | `/concession-approvals/{id}/deny` | Deny a SUBMITTED concession; denier must differ from requester | LeasingAgent, PropertyManager, RegionalDirector |
| POST | `/leases/{leaseId}/non-renewal-notices` | Create a non-renewal notice (DRAFT) for cause | LeasingAgent, PropertyManager, RegionalDirector |
| GET | `/non-renewal-notices` | List non-renewal notices with filters | PlatformAdmin, RegionalDirector, PropertyManager, LeasingAgent |
| GET | `/non-renewal-notices/{id}` | Get a non-renewal notice | PlatformAdmin, RegionalDirector, PropertyManager, LeasingAgent |
| POST | `/non-renewal-notices/{id}/serve` | Serve a DRAFT notice; statutory lead time, effective date, segregation of duties, and repositioning quota enforced | PropertyManager, RegionalDirector |
| POST | `/non-renewal-notices/{id}/rescind` | Rescind a SERVED notice within the cure window; restores lease status verbatim | PropertyManager, RegionalDirector |
| GET | `/renewal-documents` | List renewal documents with filters | PlatformAdmin, RegionalDirector, PropertyManager, LeasingAgent, Resident |
| GET | `/renewal-documents/{id}` | Get a renewal document | PlatformAdmin, RegionalDirector, PropertyManager, LeasingAgent, Resident |
| POST | `/renewal-documents/{id}/sign-resident` | Resident signs the renewal document | Resident |
| POST | `/renewal-documents/{id}/countersign` | Management countersigns: executes the renewal with final-variant rent recompute | PropertyManager, RegionalDirector |
| POST | `/renewal-documents/{id}/rescind` | Resident rescinds an executed renewal within three days of countersign; restores lease economics | Resident |

## 5. Error Code Catalogue

Trigger conditions for each error are specified throughout §2 and §3 rather than in this table.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_POLICY_NOT_FOUND` | 404 |
| `ERR_PROPERTY_NOT_FOUND` | 404 |
| `ERR_UNIT_NOT_FOUND` | 404 |
| `ERR_RESIDENT_NOT_FOUND` | 404 |
| `ERR_LEASE_NOT_FOUND` | 404 |
| `ERR_OFFER_NOT_FOUND` | 404 |
| `ERR_CONCESSION_NOT_FOUND` | 404 |
| `ERR_NOTICE_NOT_FOUND` | 404 |
| `ERR_DOCUMENT_NOT_FOUND` | 404 |
| `ERR_STALE_LEASE_VERSION` | 412 |
| `ERR_STALE_PROPERTY_VERSION` | 412 |
| `ERR_LEASE_TERM_OVERLAP` | 409 |
| `ERR_DUPLICATE_JURISDICTION` | 409 |
| `ERR_DUPLICATE_UNIT_NUMBER` | 409 |
| `ERR_LEASE_NOT_ISSUABLE` | 409 |
| `ERR_OFFER_NOT_DRAFT` | 409 |
| `ERR_OFFER_NOT_ISSUED` | 409 |
| `ERR_OFFER_NOT_COUNTERED` | 409 |
| `ERR_OFFER_NOT_WITHDRAWABLE` | 409 |
| `ERR_DOCUMENT_INVALID_STATE` | 409 |
| `ERR_NOTICE_NOT_DRAFT` | 409 |
| `ERR_NOTICE_NOT_SERVED` | 409 |
| `ERR_CONCESSION_NOT_SUBMITTED` | 409 |
| `ERR_RENT_CAP_EXCEEDED` | 422 |
| `ERR_NOTICE_WINDOW_MISSED` | 422 |
| `ERR_INSUFFICIENT_NOTICE_LEAD` | 422 |
| `ERR_INVALID_EFFECTIVE_DATE` | 422 |
| `ERR_TERM_OUTSIDE_STAGGERING_BAND` | 422 |
| `ERR_MAX_NEGOTIATION_ROUNDS` | 409 |
| `ERR_CONCESSION_APPROVAL_REQUIRED` | 409 |
| `ERR_CONCESSION_TIER_EXCEEDED` | 403 |
| `ERR_CONCESSION_EXCEEDS_ABSOLUTE_MAX` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_REPOSITIONING_QUOTA_EXCEEDED` | 422 |
| `ERR_RESCISSION_WINDOW_LAPSED` | 409 |
