# Rent Board & Rent-Stabilization API — Product Requirements Document

## 1. Introduction

Municipal rent boards administer a dense web of rent-stabilization rules: every regulated unit carries a registered base rent, a lawful ceiling that may only move within an annually published adjustment, and a paper trail of registrations, petitions, hearings, service complaints, buyout offers, and compliance penalties. Landlords, tenants, hearing officers, and board staff all touch the same records, and a single mistake — an increase above the allowable ceiling, a buyout completed before the cooling-off window closes, a penalty confirmed by the same officer who assessed it — can invalidate an entire regulatory action.

This document specifies a REST API that models that regulatory lifecycle end to end. It covers unit registration and base-rent capture, allowable annual increases with rent banking, capital-improvement and hardship petitions adjudicated through scheduled hearings, tenant service-reduction claims that temporarily reduce lawful rent, buyout-and-relocation filings governed by a cooling-off window and an escrow conservation invariant, exemption and vacancy-decontrol decisions, and the compliance-penalty ledger. The system is designed so that the lawful rent of a unit is always derivable from its history, so that every monetary computation is reproducible to the cent, and so that operations that must be performed by different people (four-eyes) or in the correct order (state machines, cooling-off, optimistic concurrency) cannot be short-circuited.

The audience for this document is the engineering team implementing the service. It leads with domain behavior and defers the transport contract — endpoint paths and status codes — to the reference tables in Sections 4 and 5.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the principal's role. If either header is missing or does not name a recognized role, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but is not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

There are exactly five roles, spelled precisely as follows: `Landlord`, `Tenant`, `HearingOfficer`, `RentBoardClerk`, and `ComplianceOfficer`.

Three roles are **entity-backed**, meaning `X-User-ID` is the `id` of a persisted actor and is used for ownership checks:

- When `X-User-Role` is `Landlord`, `X-User-ID` is the `id` of the acting `Landlord`. Ownership checks on any resource that references a landlord (a `Unit` via `landlord_id`, and any `Petition`, `Buyout`, `Registration`, `Tenancy`, rent-adjustment, or exemption request reached through that unit or naming that landlord) compare the resource's landlord to `X-User-ID`.
- When `X-User-Role` is `Tenant`, `X-User-ID` is the `id` of the acting `Tenant`. Ownership checks on a `ServiceClaim` or a `Buyout` rescission compare the resource's `tenant_id` to `X-User-ID`.
- When `X-User-Role` is `HearingOfficer`, `X-User-ID` is the `id` of the acting `HearingOfficer`.

Two roles are **opaque**: `X-User-ID` is an operator identifier not tied to any persisted entity and is never compared to a resource's `id`.

- When `X-User-Role` is `RentBoardClerk`, `X-User-ID` is an opaque administrative operator identifier. The board clerk onboards actors, publishes adjustments, schedules hearings, completes buyouts, and drives the logical clock.
- When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque regulatory operator identifier. The server records it — as `assessed_by` when a penalty is assessed and as `confirmed_by` when a penalty is confirmed — but does not compare it to any entity's `id`. It is compared only to the *other* compliance officer's identifier for the four-eyes rule (see §2.9).

When an owner-scoped operation is invoked by the correct role but by a principal who does not own or is not a party to the target resource, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership check applies to applying a rent adjustment to a unit, creating a tenancy, all petition operations, all buyout operations, creating a service claim, and rescinding a buyout.

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

List endpoints accept two optional query parameters, `limit` and `offset`. `limit` defaults to 10, has a minimum of 1, and a maximum of 100; a supplied value outside this range is invalid. `offset` defaults to 0 and has no upper bound beyond the size of the collection. Results are always ordered by `created_at` ascending (oldest first). The `meta` block of a list response reports `limit`, `offset`, `total_count` (the full count of matching resources before the page window is applied), and `has_more` (true when more resources exist beyond the current page).

### 2.4. Common Resource Properties and Identifiers

Most resources carry four common properties. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits: `created_at` is stamped at creation, and `updated_at` is refreshed on every mutation. `version` is an integer that starts at 1 and increments by one on every mutation of the resource.

One entity is an exception. An `AGADetermination` carries only `id` and `created_at`; it has neither `updated_at` nor `version`, because a published Annual General Adjustment is immutable once created.

All timestamps that the system produces — `created_at`, `updated_at`, `filed_at`, `rescind_deadline` — are rendered from the server's **logical clock** (see §2.7), never from wall-clock time.

### 2.5. Optimistic Concurrency Control on Units

Two operations mutate a `Unit`'s regulatory state in ways that could silently clobber a change the caller never saw, so both are guarded by optimistic concurrency control keyed on the unit's `version`.

Filing an annual registration for a unit requires the request to carry `expected_unit_version`, the unit `version` the client last observed. If that value does not equal the unit's current `version` — because another registration or a rent adjustment has advanced the unit since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), rather than superseding an active registration the client never observed.

Applying an allowable-increase rent adjustment likewise requires `expected_unit_version` in the request body. If it does not equal the unit's current `version` — because a prior adjustment, a passthrough grant, or a service decrease has already changed the lawful rent — the adjustment is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes a version field. Both guarded operations increment `Unit.version` by one on success.

### 2.6. Monetary Precision, Rounding, and Rent Cascades

All monetary amounts are stored and returned as integer cents. Wherever a computation produces a fractional cent, the result is rounded **half-up** to the nearest whole cent. The one accumulator that is not a monetary amount, a unit's `banked_pct`, is a fraction carried to four decimal places and rounded half-up at four decimals. The escrow conservation quantity `escrow_committed_cents` is exact-integer arithmetic with no rounding.

A unit's `current_lawful_rent_cents` is the single source of truth for what may lawfully be charged. Whenever it changes — through an allowable increase, a petition passthrough grant, a substantiated service decrease, or a restoration — the change **cascades** to the unit's `ACTIVE` tenancy: that tenancy's `monthly_rent_cents` is set to the unit's new lawful rent in the same operation. A tenancy's `monthly_rent_cents` is thus always a mirror of the unit's lawful rent at the time of the last change, and is never set directly by a caller.

### 2.7. The Logical Clock and Temporal Deadlines

The server maintains a logical clock used for every timestamp it stamps and every temporal comparison it makes. On startup the clock reads exactly `2026-05-01T00:00:00Z` and never falls back to wall-clock time. A board clerk may advance it by supplying a `to_iso8601` instant to the clock-set capability; the clock then reads that instant until advanced again. Buyout cooling-off deadlines, rescission eligibility, and completion eligibility are all evaluated against this logical clock, so tests can deterministically move time forward.

### 2.8. Validation Order and Existence Resolution

When a request could fail multiple checks, the checks are evaluated in a fixed priority order so that the returned `error_id` is deterministic:

1. **Authentication** — headers present and valid, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the role may invoke this endpoint, else `ERR_UNAUTHORIZED` (403).
3. **Ownership** — for owner-scoped operations, the acting entity-backed principal owns or is party to the resource, else `ERR_NOT_RESOURCE_OWNER` (403).
4. **Existence** — every path id and every foreign-key reference in the body resolves to an existing resource, evaluated left to right. A missing resource yields the entity-specific not-found error: `ERR_UNIT_NOT_FOUND`, `ERR_LANDLORD_NOT_FOUND`, `ERR_TENANT_NOT_FOUND`, `ERR_HEARING_OFFICER_NOT_FOUND`, `ERR_PETITION_NOT_FOUND`, `ERR_HEARING_NOT_FOUND`, `ERR_SERVICE_CLAIM_NOT_FOUND`, `ERR_BUYOUT_NOT_FOUND`, `ERR_EXEMPTION_NOT_FOUND`, or `ERR_PENALTY_NOT_FOUND` (all 404).
5. **Field validation** — required fields present and well-typed, enum values valid, and type-specific fields present (for example, a capital petition must carry cost and amortization months; a hardship petition must carry a requested percentage; an overcharge penalty must carry months and monthly amount). A failure here is `ERR_VALIDATION` (400).
6. **State** — the target resource is in a state from which the requested transition is defined, else `ERR_INVALID_STATE` (409).

Beyond these six shared checks, endpoint-specific state, temporal, referential, and fiscal checks follow in the priority listed here: unit-stabilized (`ERR_UNIT_NOT_STABILIZED`), petition-under-review (`ERR_PETITION_NOT_UNDER_REVIEW`), unit-vacant for decontrol (`ERR_UNIT_NOT_VACANT`), segregation of duties (`ERR_SOD_VIOLATION`), disclosure required (`ERR_DISCLOSURE_REQUIRED`), cooling-off-expired (`ERR_COOLING_OFF_EXPIRED`), cooling-off-not-elapsed (`ERR_COOLING_OFF_NOT_ELAPSED`), tenant-not-linked (`ERR_TENANT_NOT_LINKED`), unit-occupied (`ERR_UNIT_OCCUPIED`), officer-unavailable (`ERR_OFFICER_UNAVAILABLE`), relocation-below-minimum (`ERR_RELOCATION_BELOW_MINIMUM`), decontrol-threshold-not-met (`ERR_DECONTROL_THRESHOLD_NOT_MET`), increase-exceeds-allowable (`ERR_INCREASE_EXCEEDS_ALLOWABLE`), no-AGA-determination (`ERR_NO_AGA_DETERMINATION`), invalid-grant-amount (`ERR_INVALID_GRANT_AMOUNT`), and finally the optimistic-concurrency check (`ERR_STALE_VERSION`). The trigger conditions for each of these live in the workflow narratives of §3.

Nested read paths validate left to right: to list a unit's registrations or a unit's exemptions, the unit id in the path must resolve first.

### 2.9. Segregation of Duties and the Escrow Conservation Invariant

Two safety mechanisms cut across the domain. First, **four-eyes** on penalties: the `ComplianceOfficer` who confirms a penalty (recorded as `confirmed_by`) must be a different principal from the one who assessed it (recorded as `assessed_by`). A confirmation whose `X-User-ID` equals `assessed_by` is rejected with `ERR_SOD_VIOLATION` (HTTP 403).

Second, the **escrow conservation invariant**. Each landlord carries `escrow_committed_cents`, a computed running total that must, after every buyout mutation, exactly equal the sum of `relocation_amount_cents` across that landlord's buyouts currently in `FILED` state. Filing a buyout adds its relocation amount to the landlord's committed escrow; rescinding or completing a filed buyout subtracts that same amount back out. Because each buyout contributes its relocation amount exactly once while `FILED` and removes it exactly once when it leaves `FILED`, the committed total is a conserved quantity.

## 3. Business Logic & Workflows

### 3.1. Onboarding actors and publishing the Annual General Adjustment

Before any regulatory activity, the board clerk onboards the parties. A `Landlord` is created with a `name`, a unique `email`, and a `business_license_no`; the landlord's `escrow_committed_cents` begins at 0. A `Tenant` is created with a `name`, a unique `email`, and a `phone`. A `HearingOfficer` is created with a `name`, a unique `email`, and an optional `active` flag that defaults to true when omitted and marks whether the officer may be scheduled.

The clerk also publishes each year's **Annual General Adjustment**, the ceiling on ordinary rent increases. A published adjustment records the `effective_year` it governs (unique across adjustments), the informational `cpi_pct` (the published CPI change fraction), the binding `aga_pct` (the allowable general-adjustment fraction, for example a value of 0.03 for three percent, and never negative), and the `effective_from` and `effective_to` dates bounding its applicability. Landlords may list published adjustments, optionally filtering by `effective_year`.

The board clerk alone may drive the logical clock forward by supplying a `to_iso8601` instant, an administrative test-driving capability described in §2.7.

### 3.2. Registering a unit and filing annual registrations

A landlord (or the board clerk on their behalf) registers a rental unit by supplying its `landlord_id`, its `address`, its `bedrooms` count (zero or greater), and its `base_rent_cents` (strictly greater than zero). At creation the unit's `current_lawful_rent_cents` is initialized to `base_rent_cents`, its `banked_pct` is 0, its `stabilization_status` is `STABILIZED`, and its `decrease_active` flag is false. Anyone with a legitimate interest may fetch a unit or list units filtered by `landlord_id`.

Each calendar year the unit's rent is declared to the registry. Filing a registration supplies the `registration_year`, the `declared_rent_cents` for that year (strictly greater than zero), and — because this is one of the two version-guarded operations — the `expected_unit_version`. On success the registration is created in `ACTIVE` status and its `filed_by` is set to the filing principal's `X-User-ID` for audit. Each unit has at most one `ACTIVE` registration: if a prior `ACTIVE` registration already exists for the unit, filing a new one transitions that prior registration from `ACTIVE` to `SUPERSEDED`, and the unit's `version` is incremented by one. Should the supplied `expected_unit_version` not match the unit's current `version`, the filing is rejected with `ERR_STALE_VERSION` before any supersession occurs. A unit's registrations may be listed through the unit; the path unit id resolves first.

### 3.3. Applying an allowable annual increase and banking unused headroom

A landlord raises a unit's lawful rent through a **rent adjustment**. The request carries the `effective_date` of the increase, the `proposed_new_rent_cents` the landlord wants to charge, an `apply_banked` flag indicating whether to draw on previously banked headroom, and the `expected_unit_version` for the concurrency check. The unit must be `STABILIZED`; an adjustment against an `EXEMPT` or `DECONTROLLED` unit is rejected with `ERR_UNIT_NOT_STABILIZED`.

The system first selects the Annual General Adjustment whose `effective_year` equals the calendar year of the `effective_date`. If no adjustment has been published for that year, the request is rejected with `ERR_NO_AGA_DETERMINATION`. Let the prior lawful rent be the unit's current `current_lawful_rent_cents`. The allowable fraction depends on `apply_banked`. When `apply_banked` is false (the **standard** path), the allowable fraction is exactly that year's `aga_pct`. When `apply_banked` is true (the **banked** path), the allowable fraction is the smaller of two quantities: the sum of that year's `aga_pct` and the unit's current `banked_pct`, or the banking cap of 0.16 (sixteen percent) — that is, the combined draw may never push the allowable fraction above sixteen percent. The maximum new rent is the prior lawful rent multiplied by one plus the allowable fraction, rounded half-up to whole cents.

The proposed new rent is validated against a two-sided boundary: it may not exceed the maximum new rent, and it may not fall below the prior lawful rent (this operation only raises rent). A proposed rent equal to the maximum is allowed; a proposed rent above the maximum, or below the prior lawful rent, is rejected with `ERR_INCREASE_EXCEEDS_ALLOWABLE`.

On success the unit's `current_lawful_rent_cents` becomes the proposed new rent, and the banking accumulator is updated symmetrically according to which path was taken. Define the taken fraction as the proposed new rent minus the prior lawful rent, divided by the prior lawful rent. On the standard path, the unused headroom is the year's `aga_pct` minus the taken fraction, floored at zero; that unused headroom is added to `banked_pct`, and the result is rounded to four decimals and then capped at 0.16. On the banked path, the amount consumed from the bank is the taken fraction minus the year's `aga_pct`, floored at zero; that consumed amount is subtracted from `banked_pct`, and the result is rounded to four decimals and floored at zero. The adjustment then cascades to the unit's `ACTIVE` tenancy (its `monthly_rent_cents` becomes the new lawful rent) and increments `Unit.version` by one.

### 3.4. Leasing units and ending tenancies

A tenancy is created on a `STABILIZED` unit by supplying the `unit_id`, the `tenant_id`, a `start_date`, and an optional `end_date` (the occupancy end, exclusive; omitted or null for an open-ended lease). Creating a tenancy on a non-stabilized unit is rejected with `ERR_UNIT_NOT_STABILIZED`. The requested occupancy interval runs from `start_date` inclusive to `end_date` exclusive; it may not overlap any existing `ACTIVE` tenancy on the same unit. Two intervals that merely touch — one starting exactly at the instant a prior one ends — do not overlap and are allowed; a genuine overlap is rejected with `ERR_UNIT_OCCUPIED`. On creation the new tenancy's `monthly_rent_cents` is set to the unit's current `current_lawful_rent_cents`, and its `status` is `ACTIVE`. Tenancies may be listed filtered by `unit_id` and/or `tenant_id`.

A landlord (or the board clerk) ends an `ACTIVE` tenancy; the transition moves `status` from `ACTIVE` to `ENDED` and sets `end_date` from the payload if supplied, or from the logical clock date otherwise. A tenancy also ends as a side effect of a completed buyout (see §3.7).

### 3.5. Petitions, hearings, and rent passthroughs

When a landlord wants an increase beyond the ordinary annual adjustment, they file a **petition** against a unit. A petition names its `unit_id`, its `landlord_id`, and its `petition_type`, which is either `CAPITAL_IMPROVEMENT` or `HARDSHIP`. A capital-improvement petition must also carry the `requested_cost_cents` (the total improvement cost) and the `amortization_months` over which that cost is spread; a hardship petition must carry the `requested_pct` it seeks. A petition begins life in `DRAFT` with `granted_amount_cents` of 0 and `revision_count` of 0.

**The petition lifecycle.** The petitioning landlord submits a `DRAFT` petition, moving it `DRAFT → SUBMITTED`. A hearing officer takes it up for review (`SUBMITTED → UNDER_REVIEW`). From review the officer may send it back to the landlord for changes (`UNDER_REVIEW → NEEDS_REVISION`), optionally recording a `reason`; the landlord then resubmits (`NEEDS_REVISION → SUBMITTED`), and each such resubmission increments `revision_count` by one. This revision loop — `UNDER_REVIEW → NEEDS_REVISION → SUBMITTED → UNDER_REVIEW` — may cycle any number of times. Alternatively, from `UNDER_REVIEW` the board clerk schedules a hearing, moving the petition `UNDER_REVIEW → HEARING_SCHEDULED`; scheduling requires the petition to be `UNDER_REVIEW`, otherwise `ERR_PETITION_NOT_UNDER_REVIEW`.

**Scheduling a hearing.** Scheduling supplies the `officer_id`, a `scheduled_start`, and a `scheduled_end` (which must be after `scheduled_start`). The named officer must be free: a request is rejected with `ERR_OFFICER_UNAVAILABLE` if any `SCHEDULED` hearing already assigned to that officer conflicts with the requested window once a thirty-minute buffer is applied. Concretely, treating each hearing window as half-open, a conflict exists when the requested start is earlier than the existing hearing's end extended by thirty minutes, **and** the existing hearing's start is earlier than the requested end extended by thirty minutes. A request whose start falls exactly at an existing hearing's end plus thirty minutes does not conflict and is allowed. On success a `Hearing` is created in `SCHEDULED` status with a null `decision`, and the petition moves to `HEARING_SCHEDULED`. Hearings may be listed filtered by `petition_id` and/or `officer_id`.

**Deciding the hearing and the passthrough calculation.** The assigned hearing officer records a `decision` of `GRANT`, `PARTIAL`, or `DENY`; deciding requires the hearing to be `SCHEDULED` and its petition to be `HEARING_SCHEDULED`. The decision drives the *full passthrough*, computed from the petition and its unit as follows.

- For a `CAPITAL_IMPROVEMENT` petition, the monthly amortized cost is the `requested_cost_cents` divided by `amortization_months`, rounded half-up to whole cents. A monthly cap is then taken as a bedroom-tiered fraction of the unit's `base_rent_cents`: five percent when the unit has one bedroom or fewer, six percent when it has two or three bedrooms, and seven percent when it has four or more bedrooms; that fraction of `base_rent_cents` is rounded half-up to whole cents. The full passthrough is the smaller of the monthly amortized cost and this monthly cap.
- For a `HARDSHIP` petition, the requested amount is the unit's `current_lawful_rent_cents` multiplied by the petition's `requested_pct`, rounded half-up. A hardship cap is the unit's `current_lawful_rent_cents` multiplied by 0.08 (eight percent), rounded half-up. The full passthrough is the smaller of the requested amount and the hardship cap.

On a `GRANT`, `petition.granted_amount_cents` is set to the full passthrough. On a `PARTIAL`, the officer supplies `granted_amount_cents`, which must be strictly greater than zero and strictly less than the full passthrough — anything outside that open interval is rejected with `ERR_INVALID_GRANT_AMOUNT` — and `petition.granted_amount_cents` is set to that supplied amount. On a `DENY`, `petition.granted_amount_cents` stays 0 and no rent changes. For both `GRANT` and `PARTIAL`, the hearing moves to `HELD` with its `decision` recorded, the petition transitions to `GRANTED` or `PARTIAL` respectively, the granted amount is **added** to the unit's `current_lawful_rent_cents`, and that new lawful rent cascades to the unit's `ACTIVE` tenancy. A `DENY` moves the hearing to `HELD` and the petition to `DENIED` with no monetary effect.

### 3.6. Service-reduction claims, decreases, and restoration

A tenant who loses services files a **service claim** against their unit, supplying the `unit_id`, their own `tenant_id`, a `claim_type` of `HEAT`, `WATER`, `MAINTENANCE`, or `PEST`, and a `severity` of `MINOR` or `SUBSTANTIAL`. The claiming tenant must be the unit's currently `ACTIVE` tenant — that is, an `ACTIVE` tenancy must link this `tenant_id` and `unit_id` — otherwise the claim is rejected with `ERR_TENANT_NOT_LINKED`. A new claim begins in `OPEN` status with a null `ordered_decrease_pct`, a `decrease_amount_cents` of 0, and a null `pre_decrease_rent_cents`. Claims may be listed filtered by `unit_id` and/or `tenant_id`.

A hearing officer (or the board clerk) opens an investigation, moving the claim `OPEN → INVESTIGATING`. From investigation the hearing officer records a `disposition`. A `DISMISS` disposition moves the claim `INVESTIGATING → DISMISSED` with no rent change. A `SUBSTANTIATE` disposition, which additionally requires the unit still to have an `ACTIVE` tenancy for the claiming tenant, moves the claim `INVESTIGATING → SUBSTANTIATED` and applies a rent decrease: it snapshots the unit's current `current_lawful_rent_cents` into the claim's `pre_decrease_rent_cents`, sets `ordered_decrease_pct` from severity — twenty-five percent for `SUBSTANTIAL`, ten percent for `MINOR` — computes `decrease_amount_cents` as the snapshotted pre-decrease rent multiplied by that fraction and rounded half-up, subtracts that decrease amount from the unit's `current_lawful_rent_cents`, sets the unit's `decrease_active` flag to true, and cascades the decreased lawful rent to the unit's `ACTIVE` tenancy.

Once services are restored, the board clerk (or a hearing officer) restores the claim, moving it `SUBSTANTIATED → RESTORED`; this requires the unit's `decrease_active` flag to be true. Restoration is a compensating action: it sets the unit's `current_lawful_rent_cents` back to exactly the claim's `pre_decrease_rent_cents`, clears `decrease_active` to false, and cascades the restored lawful rent to the unit's `ACTIVE` tenancy. Because restoration reinstates the exact snapshot rather than re-adding the decrease amount, the unit's lawful rent returns precisely to its pre-decrease value.

### 3.7. Buyouts, cooling-off, and relocation escrow

A landlord may offer a tenant a **buyout**. The offer is created with the `unit_id`, the offering `landlord_id`, the target `tenant_id`, the `offer_amount_cents` (strictly greater than zero), and the `relocation_amount_cents` (zero or greater), and it begins in `DRAFT` with `disclosure_acknowledged` false, a null `filed_at`, and a null `rescind_deadline`. The target tenant must be the unit's `ACTIVE` tenant, or the creation is rejected with `ERR_TENANT_NOT_LINKED`. Buyouts may be listed filtered by `unit_id`, `landlord_id`, and/or `tenant_id`.

**Filing.** The landlord files the buyout, supplying `disclosure_acknowledged` in the payload, which moves it `DRAFT → FILED`. Filing has two guards: the tenant-rights disclosure must be acknowledged — a filing where `disclosure_acknowledged` is not true is rejected with `ERR_DISCLOSURE_REQUIRED` — and the `relocation_amount_cents` must be at least the relocation floor of 500000 cents (five thousand dollars); a value one cent below the floor is rejected with `ERR_RELOCATION_BELOW_MINIMUM`, while a value exactly at the floor is accepted. On success the buyout records `disclosure_acknowledged` from the payload, sets `filed_at` to the current logical-clock instant, computes `rescind_deadline` as `filed_at` plus thirty days, and adds the `relocation_amount_cents` to the landlord's `escrow_committed_cents`.

**The cooling-off fork.** A filed buyout resolves to exactly one of two divergent outcomes. The **tenant** may rescind while the cooling-off window is open — that is, while the current logical time is at or before the `rescind_deadline`; a rescission attempted after that instant is rejected with `ERR_COOLING_OFF_EXPIRED`. Rescission moves the buyout `FILED → RESCINDED`, subtracts the `relocation_amount_cents` back out of the landlord's `escrow_committed_cents`, and leaves the tenancy untouched (the tenant keeps the unit). Conversely, the **board clerk** may complete the buyout only once the cooling-off window has elapsed — that is, when the current logical time is at or after the `rescind_deadline`; a completion attempted before that instant is rejected with `ERR_COOLING_OFF_NOT_ELAPSED`. Completion moves the buyout `FILED → COMPLETED`, subtracts the `relocation_amount_cents` back out of the landlord's `escrow_committed_cents`, and cascades to the tenancy: the tenant's `ACTIVE` tenancy on the unit transitions to `ENDED` with its `end_date` set to the completion date. Both branches release the same committed escrow; only completion vacates the unit.

### 3.8. Exemptions and vacancy decontrol

A landlord requests removal of a unit from stabilization by filing an **exemption**, supplying the `unit_id`, the `exemption_type`, and — for a vacancy filing — the `vacancy_rent_cents` and an optional `effective_date`. The `exemption_type` is one of `SUBSTANTIAL_REHAB`, `OWNER_OCCUPIED`, `VACANCY_DECONTROL`, or `NEW_CONSTRUCTION`. A new exemption is `REQUESTED` with a null `effective_date` until decided. A unit's exemptions may be listed through the unit.

A compliance officer decides the exemption with a `decision` of `APPROVE` or `DENY` and an optional `effective_date`. Deciding requires the exemption to be `REQUESTED` and the unit to be `STABILIZED`. A `DENY` leaves the unit's status unchanged. An `APPROVE` records the exemption's `effective_date` from the payload and changes the unit's `stabilization_status`, with the target depending on type. For `SUBSTANTIAL_REHAB`, `OWNER_OCCUPIED`, or `NEW_CONSTRUCTION`, the unit moves from `STABILIZED` to `EXEMPT`. For `VACANCY_DECONTROL`, two additional gates apply: the unit must have no `ACTIVE` tenancy (a decontrol approval on an occupied unit is rejected with `ERR_UNIT_NOT_VACANT`), and the exemption's `vacancy_rent_cents` must be at least the decontrol threshold of 500000 cents (five thousand dollars) — a value at the threshold passes, a value one cent below it is rejected with `ERR_DECONTROL_THRESHOLD_NOT_MET`. When both gates pass, approval moves the unit from `STABILIZED` to `DECONTROLLED`.

### 3.9. Compliance penalties and four-eyes confirmation

A compliance officer assesses a **penalty** against a landlord's unit by supplying the `unit_id`, the `landlord_id`, and the `penalty_type`. The type is one of `LATE_REGISTRATION`, `FAILURE_TO_FILE`, or `OVERCHARGE`. An overcharge penalty additionally carries `months_overcharged`, `monthly_overcharge_cents`, and a `willful` flag (defaulting to false). The `assessed_amount_cents` is computed at assessment time and the penalty is created in `ASSESSED` status with `assessed_by` set to the assessing officer's `X-User-ID` and a null `confirmed_by`. Penalties may be listed filtered by `unit_id` and/or `landlord_id`.

The assessed amount is computed by type. A `LATE_REGISTRATION` penalty is a flat 50000 cents (five hundred dollars). A `FAILURE_TO_FILE` penalty is a flat 100000 cents (one thousand dollars). An `OVERCHARGE` penalty starts from a base equal to `months_overcharged` multiplied by `monthly_overcharge_cents`. When the overcharge is `willful`, the assessed amount is that base multiplied by three (treble damages, with no interest component). When it is not willful, interest is added: the per-month interest is `monthly_overcharge_cents` multiplied by the monthly interest rate of 0.0075 (three-quarters of one percent), rounded half-up to whole cents; that per-month interest is then multiplied by `months_overcharged` to give the total interest, and the assessed amount is the base plus that total interest. The rounding order is pinned: interest is rounded to whole cents **per month first and then multiplied by the month count**, not summed and rounded once.

A penalty is finalized by a second compliance officer confirming it, moving it `ASSESSED → CONFIRMED` and recording `confirmed_by` as the confirming officer's `X-User-ID`. The confirming officer must differ from the assessor: a confirmation whose `X-User-ID` equals the penalty's `assessed_by` is rejected with `ERR_SOD_VIOLATION`.

## 4. Endpoint Definitions

New-resource creation returns HTTP 201; state transitions, mutations, reads, and the clock-set capability return HTTP 200. All request and response bodies follow the envelope in §2.2; consult the §3 narratives to reconstruct each endpoint's payload and side effects.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | `/rent-board/landlords` | Create a landlord | RentBoardClerk |
| GET | `/rent-board/landlords/{id}` | Fetch a landlord | RentBoardClerk, Landlord, ComplianceOfficer |
| POST | `/rent-board/tenants` | Create a tenant | RentBoardClerk |
| GET | `/rent-board/tenants/{id}` | Fetch a tenant | RentBoardClerk, Tenant, Landlord |
| POST | `/rent-board/hearing-officers` | Create a hearing officer | RentBoardClerk |
| GET | `/rent-board/hearing-officers/{id}` | Fetch a hearing officer | RentBoardClerk, HearingOfficer |
| POST | `/rent-board/aga-determinations` | Publish an Annual General Adjustment | RentBoardClerk |
| GET | `/rent-board/aga-determinations` | List AGA determinations (filter by `effective_year`) | RentBoardClerk, Landlord |
| POST | `/_clock/set_current_utc` | Set the server logical clock (test-driving) | RentBoardClerk |
| POST | `/rent-board/units` | Register a rental unit with its base rent | Landlord, RentBoardClerk |
| GET | `/rent-board/units/{id}` | Fetch a unit | Landlord, RentBoardClerk, Tenant, HearingOfficer, ComplianceOfficer |
| GET | `/rent-board/units` | List units (filter by `landlord_id`) | Landlord, RentBoardClerk, ComplianceOfficer |
| POST | `/rent-board/units/{id}/registrations` | File the annual registration for a unit (OCC) | Landlord, RentBoardClerk |
| GET | `/rent-board/units/{id}/registrations` | List a unit's registrations | Landlord, RentBoardClerk, ComplianceOfficer |
| POST | `/rent-board/units/{id}/rent-adjustments` | Apply an allowable annual increase (OCC) | Landlord |
| GET | `/rent-board/units/{id}/exemptions` | List a unit's exemptions | Landlord, RentBoardClerk, ComplianceOfficer |
| POST | `/rent-board/tenancies` | Create a lease/tenancy on a stabilized unit | Landlord, RentBoardClerk |
| GET | `/rent-board/tenancies/{id}` | Fetch a tenancy | Landlord, RentBoardClerk, Tenant |
| GET | `/rent-board/tenancies` | List tenancies (filter by `unit_id`/`tenant_id`) | Landlord, RentBoardClerk |
| POST | `/rent-board/tenancies/{id}/end` | End an active tenancy | Landlord, RentBoardClerk |
| POST | `/rent-board/petitions` | Create a capital-improvement or hardship petition | Landlord |
| POST | `/rent-board/petitions/{id}/submit` | Submit or resubmit a petition | Landlord |
| POST | `/rent-board/petitions/{id}/review` | Move a submitted petition into review | HearingOfficer |
| POST | `/rent-board/petitions/{id}/request-revision` | Send a petition back for revision | HearingOfficer |
| POST | `/rent-board/petitions/{id}/hearings` | Schedule a hearing for a petition under review | RentBoardClerk |
| GET | `/rent-board/petitions/{id}` | Fetch a petition | Landlord, RentBoardClerk, HearingOfficer |
| GET | `/rent-board/petitions` | List petitions (filter by `unit_id`/`landlord_id`) | Landlord, RentBoardClerk, HearingOfficer |
| POST | `/rent-board/hearings/{id}/decide` | Record the hearing decision and cascade the outcome | HearingOfficer |
| GET | `/rent-board/hearings/{id}` | Fetch a hearing | Landlord, RentBoardClerk, HearingOfficer |
| GET | `/rent-board/hearings` | List hearings (filter by `petition_id`/`officer_id`) | RentBoardClerk, HearingOfficer |
| POST | `/rent-board/service-claims` | File a service-reduction claim | Tenant |
| POST | `/rent-board/service-claims/{id}/investigate` | Open investigation on a service claim | HearingOfficer, RentBoardClerk |
| POST | `/rent-board/service-claims/{id}/decide` | Substantiate or dismiss a service claim | HearingOfficer |
| POST | `/rent-board/service-claims/{id}/restore` | Restore services and the pre-decrease rent | RentBoardClerk, HearingOfficer |
| GET | `/rent-board/service-claims/{id}` | Fetch a service claim | Tenant, Landlord, RentBoardClerk, HearingOfficer |
| GET | `/rent-board/service-claims` | List service claims (filter by `unit_id`/`tenant_id`) | Landlord, RentBoardClerk, HearingOfficer |
| POST | `/rent-board/buyouts` | Create a buyout & relocation offer | Landlord |
| POST | `/rent-board/buyouts/{id}/file` | File the buyout; start cooling-off and commit escrow | Landlord |
| POST | `/rent-board/buyouts/{id}/rescind` | Tenant rescinds within the cooling-off window | Tenant |
| POST | `/rent-board/buyouts/{id}/complete` | Complete the buyout after cooling-off; end the tenancy | RentBoardClerk |
| GET | `/rent-board/buyouts/{id}` | Fetch a buyout | Landlord, RentBoardClerk, Tenant |
| GET | `/rent-board/buyouts` | List buyouts (filter by `unit_id`/`landlord_id`/`tenant_id`) | Landlord, RentBoardClerk |
| POST | `/rent-board/exemptions` | Request an exemption / vacancy decontrol | Landlord |
| POST | `/rent-board/exemptions/{id}/decide` | Approve or deny an exemption | ComplianceOfficer |
| POST | `/rent-board/penalties` | Assess a compliance penalty | ComplianceOfficer |
| POST | `/rent-board/penalties/{id}/confirm` | Confirm an assessed penalty (four-eyes) | ComplianceOfficer |
| GET | `/rent-board/penalties/{id}` | Fetch a penalty | ComplianceOfficer, RentBoardClerk, Landlord |
| GET | `/rent-board/penalties` | List penalties (filter by `unit_id`/`landlord_id`) | ComplianceOfficer, RentBoardClerk, Landlord |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|------------------|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_VALIDATION | 400 |
| ERR_LANDLORD_NOT_FOUND | 404 |
| ERR_TENANT_NOT_FOUND | 404 |
| ERR_HEARING_OFFICER_NOT_FOUND | 404 |
| ERR_UNIT_NOT_FOUND | 404 |
| ERR_PETITION_NOT_FOUND | 404 |
| ERR_HEARING_NOT_FOUND | 404 |
| ERR_SERVICE_CLAIM_NOT_FOUND | 404 |
| ERR_BUYOUT_NOT_FOUND | 404 |
| ERR_EXEMPTION_NOT_FOUND | 404 |
| ERR_PENALTY_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_UNIT_NOT_STABILIZED | 409 |
| ERR_PETITION_NOT_UNDER_REVIEW | 409 |
| ERR_UNIT_NOT_VACANT | 409 |
| ERR_SOD_VIOLATION | 403 |
| ERR_DISCLOSURE_REQUIRED | 422 |
| ERR_COOLING_OFF_EXPIRED | 409 |
| ERR_COOLING_OFF_NOT_ELAPSED | 409 |
| ERR_TENANT_NOT_LINKED | 422 |
| ERR_UNIT_OCCUPIED | 409 |
| ERR_OFFICER_UNAVAILABLE | 409 |
| ERR_RELOCATION_BELOW_MINIMUM | 422 |
| ERR_DECONTROL_THRESHOLD_NOT_MET | 422 |
| ERR_INCREASE_EXCEEDS_ALLOWABLE | 422 |
| ERR_NO_AGA_DETERMINATION | 422 |
| ERR_INVALID_GRANT_AMOUNT | 422 |
| ERR_STALE_VERSION | 412 |
