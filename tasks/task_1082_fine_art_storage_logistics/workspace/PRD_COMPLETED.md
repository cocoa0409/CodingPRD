# Fine-Art Storage & Logistics API — Product Requirements Document

## 1. Introduction

Fine-art custody is a business of exacting margins: a single crate mislabeled, a vault slot double-booked, a loan shipped without valid customs papers, or a premium miscalculated by a fraction of a percent can each turn into six-figure liability. This document specifies the backend API for a fine-art storage and logistics operator that takes physical custody of valuable artworks on behalf of collectors, institutions, and dealers, and manages their entire lifecycle: intake and condition assessment, climate-controlled vault storage, crating and rigged transport, appraisal and insurance, outbound loans to exhibitions (including cross-border movements under an ATA carnet), private viewings, and the billing that ties every chargeable event back to the owning client.

The system is organized around a small set of peer resources linked by foreign keys rather than a deep resource hierarchy. Each artwork carries two independent status dimensions at once — where it physically is (its custody) and what shape it is in (its condition) — and much of the platform's value is in keeping those two dimensions, plus the vault-occupancy and client-balance ledgers, perfectly consistent as work orders cascade through the system. The remainder of this document defines the global contracts every endpoint honors (Section 2), the domain workflows and the business rules scattered through them (Section 3), the endpoint catalogue (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is missing, or if `X-User-Role` is not one of the known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly five roles, spelled precisely as follows:

- **`Registrar`** — the collections registrar. Registers clients and vaults, intakes artworks, files condition reports, creates appraisals and insurance policies, opens and releases storage placements, and drafts/submits loan agreements.
- **`Coordinator`** — the logistics coordinator. Builds crates, registers rigging crews, schedules and runs transport jobs, issues and transitions customs carnets, manages viewing rooms and bookings, and activates/returns loans.
- **`Approver`** — the governance approver. Approves, rejects, and cancels loan agreements, and cancels insurance policies. A segregation-of-duties rule (Section 3) forbids the same user from approving a loan they themselves submitted.
- **`BillingAdmin`** — the billing administrator. Generates invoices and issues, pays, or voids them.
- **`Client`** — the art owner. Reads its own artworks, loans, invoices, and bookings, and requests private viewings of its own artworks.

Four of the five roles carry an **opaque** identity: when `X-User-Role` is `Registrar`, `Coordinator`, `Approver`, or `BillingAdmin`, the `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record such an identifier where a workflow calls for it — for example, it writes the submitting operator's `X-User-ID` into `submitted_by_user_id` on a loan agreement at submission time — but it never compares that identifier against any entity's `id` for ownership purposes.

The `Client` role is **entity-backed**: when `X-User-Role` is `Client`, the `X-User-ID` is the `id` of the acting `Client` record. Ownership checks compare a resource's owning-client foreign key to `X-User-ID`. Concretely, a `Client` may read an artwork, loan, invoice, viewing booking (via each resource's `client_id`, or, for an artwork read reached through its owner, the artwork's `client_id`) or a client record (via that `Client`'s own `id`) only when the referenced client identifier equals `X-User-ID`; otherwise the request is rejected with `ERR_OWNERSHIP_REQUIRED` (HTTP 403). A `Client` may create a viewing booking only for its own `client_id` and its own artwork. Viewing rooms are readable by any `Client`.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10, must be at least 1, and may not exceed 100; the `offset` defaults to 0 and must be at least 0. A `limit` supplied below 1 or above 100, or an `offset` supplied below 0, is silently clamped into these bounds rather than rejected; a `limit` or `offset` that is present but not an integer is rejected with `ERR_VALIDATION`. Every list response echoes `limit` and `offset` in `meta` alongside `total_count` (the total number of matching records before the page window is applied) and `has_more` (true when records remain beyond the current window). Unless a workflow states otherwise, list results are ordered by `created_at` ascending.

### 2.4. Common Resource Properties, Identifiers, and the Logical Clock

Every resource is assigned a server-minted `id` that is a bare UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources also carry an `updated_at` timestamp (same format) and an integer `version` that begins at 1 and increments by one on every mutation of that resource. The sole exception is the condition report: a `ConditionReport` is an immutable inspection record that carries only `id` and `created_at` — it has neither `updated_at` nor `version`, because it is never modified after it is filed.

All time-dependent logic — day counts, coverage expiry, carnet validity, temporal overlap — is evaluated against a server **logical clock**, never the host wall-clock. On startup the clock reads exactly `2026-05-01T00:00:00Z`, and it holds that value until an operator advances it. A test-driving capability sets the clock to a supplied `to_iso8601` instant; every subsequent deadline, expiry, and duration calculation reads from the clock's then-current value.

### 2.5. Optimistic Concurrency Control on Artwork Valuation

Two write operations reshape an artwork's valuation state and therefore guard against stale reads with optimistic concurrency control keyed on the artwork's `version`. Creating an appraisal (the `POST /appraisals` operation) and creating an insurance policy (the `POST /policies` operation) each require a non-optional `expected_artwork_version` field carrying the client's last observed `version` of the target artwork. When the submitted `expected_artwork_version` does not equal the artwork's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

This matters because both operations legitimately supersede prior state: a new appraisal supersedes the previous `FINALIZED` appraisal and rewrites the artwork's `appraised_value_cents`, and a new policy supersedes the previous `ACTIVE` policy and rewrites the artwork's `active_policy_id`. Either mutation increments the artwork's `version` by one. A mismatched `expected_artwork_version` therefore means another writer has already advanced the valuation since the caller last read the artwork, and proceeding would overwrite a change the caller never saw. No other endpoint accepts a version field.

### 2.6. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer whole-cent quantities. Wherever a calculation produces a fractional cent, the result is rounded half-up to the nearest whole cent — a value exactly halfway between two cents rounds up. Where a formula involves several multiplicative factors, rounding is applied once, after all factors have been combined, unless a specific rule pins a different order. Day counts used for storage fees round any partial day up to a full day.

### 2.7. Validation Precedence

When several conditions could each reject a request, they are evaluated in a fixed order so that the returned `error_id` is deterministic. Authentication is checked first: a missing or unknown-role header yields `ERR_UNAUTHENTICATED`, then role permission yields `ERR_UNAUTHORIZED`, then `Client` ownership yields `ERR_OWNERSHIP_REQUIRED`. Existence of the path resource and of every referenced foreign-key id is checked next, left to right along the request, yielding `ERR_NOT_FOUND` on the first missing id. Body well-formedness follows — required fields present and enum values in range — yielding `ERR_VALIDATION`. Time-window well-formedness (`ERR_TIME_WINDOW_INVALID`) is checked before the version guard (`ERR_STALE_VERSION`), which is checked before the state-legality guard — a lifecycle request names its requested target state in a `to_status` field, and if that target is not reachable from the resource's current state the request is rejected with `ERR_INVALID_STATE`. Only after all of these do the domain-specific business rules run, and where a single operation layers several of them, the operation's own workflow narrative in Section 3 states their relative order.

### 2.8. Parallel Status Axes, Cascades, and Conserved Ledgers

An artwork is unusual in carrying two status dimensions that advance independently. Its `custody_status` — one of `IN_INTAKE`, `IN_STORAGE`, `IN_TRANSIT`, `ON_LOAN`, or `DEACCESSIONED` — tracks physical whereabouts. Its `condition_status` — one of `SOUND`, `MINOR_DAMAGE`, or `MAJOR_DAMAGE` — tracks conservation state and evolves on its own timeline driven entirely by condition reports. Neither axis constrains the transitions of the other, but both feed into the guards that gate transport, loans, and viewings.

Because resources are coupled by foreign key rather than nesting, a single state change frequently cascades across entities, and every such cascade must complete atomically. Whenever a mutation changes a resource, its `updated_at` is refreshed and its `version` is incremented; this applies equally to a resource mutated as the direct target of a request and to a resource mutated as the downstream target of a cascade. Two running totals are maintained as **conserved ledgers**: a vault's `occupied_slots` always equals the count of that vault's placements currently in `ACTIVE` status, and a client's `outstanding_balance_cents` always equals the sum of `total_cents` across that client's invoices currently in `ISSUED` status. Every operation that could change either total adjusts it in lockstep, so the stored value never drifts from the definition.

Nested reads are validated left to right: for any path that names a resource id, the id must resolve to an existing resource before the operation proceeds, and a foreign-key id referenced in a body is validated in the order it appears, each missing id surfacing as `ERR_NOT_FOUND`.

### 2.9. Temporal Windowing for Shared Resources

Two resources are exclusive in time. A rigging crew may hold only one transport job in a given window, and a viewing room may hold only one confirmed booking in a given window; the two use deliberately different overlap rules.

For **crews**, a newly scheduled transport job is checked against every other job on the same crew that is in `SCHEDULED` or `IN_PROGRESS` status, using closed intervals padded by a one-hour setup buffer (60 minutes) on each side. The new job conflicts when its start is earlier than the other job's end plus 60 minutes, and simultaneously its end plus 60 minutes is later than the other job's start. Adjacency that falls inside the 60-minute buffer conflicts; a clear gap of exactly 60 minutes does not. A conflict is rejected with `ERR_CREW_UNAVAILABLE`.

For **viewing rooms**, a booking being confirmed is checked against every other `CONFIRMED` booking on the same room using half-open intervals `[scheduled_start, scheduled_end)` with no buffer: the two conflict when the new booking's start is earlier than the existing booking's end and the existing booking's start is earlier than the new booking's end. Because the intervals are half-open, a new booking whose start equals a prior booking's end does not conflict. A conflict is rejected with `ERR_ROOM_UNAVAILABLE`.

For every interval-bearing request — transport jobs, storage placements, insurance policies, viewing bookings, loans, and carnets — the end instant must be strictly after the start instant (a transport or booking's `scheduled_end` after its `scheduled_start`, a policy's `effective_end` after its `effective_start`, a placement's `scheduled_end_at` after its `start_at`), or the request is rejected with `ERR_TIME_WINDOW_INVALID`.

## 3. Business Logic & Workflows

### 3.1. Clients, Vaults, and Artwork Intake

A `Registrar` opens the platform for a collector by registering a client, supplying the owner's `name`, the `client_type` (`INDIVIDUAL`, `INSTITUTION`, or `DEALER`), and a `billing_email`; the caller may also set `credit_terms_days`, which defaults to 30 net days when omitted. A newly registered client starts with `account_status` of `ACTIVE` and an `outstanding_balance_cents` of 0. The registrar can later suspend a client, moving `account_status` from `ACTIVE` to `SUSPENDED`, and reactivate it back to `ACTIVE`; both directions are always permitted.

Vaults are the climate-controlled homes for stored works. Creating a vault records its `name`, its `climate_class` (`AMBIENT`, `COOL`, or `COLD`), and its `capacity_slots`, which must be at least 1. A vault may optionally declare a `temp_setpoint_c` (defaulting to 20 degrees Celsius) and a `humidity_setpoint_pct` (defaulting to 50 percent relative humidity). It begins life with `status` `OPERATIONAL` and `occupied_slots` of 0. A vault can be taken to `MAINTENANCE` and returned to `OPERATIONAL` freely. It can be permanently `DECOMMISSIONED` from `OPERATIONAL`, but only when it holds no active occupants — if its `occupied_slots` is not zero, the decommission is rejected with `ERR_INVALID_STATE`. `DECOMMISSIONED` is terminal.

Artwork intake captures the piece itself. A registrar records the owning `client_id`, the `title`, the `artist`, and optionally the `medium` and `year`, together with three classification bands: `size_class` (`SMALL`, `MEDIUM`, or `LARGE`, which drives the storage size multiplier), `fragility_class` (`LOW`, `MEDIUM`, or `HIGH`, which drives the insurance multiplier), and the required `climate_class` (`AMBIENT`, `COOL`, or `COLD`) the piece must be stored in. On intake, the work's `custody_status` is `IN_INTAKE`, its `condition_status` is `SOUND`, and its `appraised_value_cents` is 0; its `active_policy_id` is unset until coverage is written. A registrar may deaccession a work — transitioning `custody_status` to the terminal `DEACCESSIONED` — but only while it is `IN_STORAGE`; from any other custody state the request is rejected with `ERR_INVALID_STATE`.

### 3.2. Storage Placement and Occupancy

Placing a work in a vault is how it first enters storage. A registrar creates a placement referencing the `artwork_id` and `vault_id`, a `start_at`, and a `scheduled_end_at` that anchors the forward-looking fee projection. The system rejects the placement, in this order, when the window is malformed (`scheduled_end_at` not strictly after `start_at`, `ERR_TIME_WINDOW_INVALID`); when the artwork's required `climate_class` does not equal the vault's `climate_class` (`ERR_CLIMATE_MISMATCH`); when the vault is not `OPERATIONAL` (`ERR_VAULT_UNAVAILABLE`); and when the vault is already full, meaning its `occupied_slots` is greater than or equal to its `capacity_slots` (`ERR_VAULT_FULL`). A successful placement is created in `status` `ACTIVE`, increments the vault's `occupied_slots` by one, and, when the artwork was still `IN_INTAKE`, advances its `custody_status` to `IN_STORAGE`.

At creation the placement's forward-looking fee is projected. The provisional fee counts the number of days from `start_at` to `scheduled_end_at`, computed as the difference in 24-hour days with any partial day rounded up to a whole day. It multiplies that day count by the vault's climate daily rate — 500 cents per day for an `AMBIENT` vault, 800 cents per day for `COOL`, and 1,200 cents per day for `COLD` — and by the artwork's size multiplier — 1.0 for `SMALL`, 1.5 for `MEDIUM`, and 2.0 for `LARGE` — and rounds the product half-up to whole cents, storing it as `provisional_fee_cents`. The `final_fee_cents` remains unset until release.

A registrar releases a placement by transitioning it to the terminal `RELEASED` status, permitted from either `ACTIVE` or `SUSPENDED`. Release sets `released_at` to the current logical-clock time and computes `final_fee_cents` by the same formula as the provisional fee, except the day count runs chronologically from `start_at` to `released_at` (again rounding any partial day up) rather than to the scheduled end. When the placement was `ACTIVE` at release, the vault's `occupied_slots` is decremented by one; when it was already `SUSPENDED`, the slot was surrendered earlier and `occupied_slots` is left unchanged. A vault's `occupied_slots` is, by definition, the count of its placements in `ACTIVE` status, and it is kept in step through every placement status change.

A placement is also suspended and resumed automatically as its artwork goes on and off loan — see Section 3.6 — and when a suspended placement is resumed it can only return to `ACTIVE` if the vault still has room; if the vault has since filled to capacity the resume is rejected with `ERR_VAULT_FULL`.

### 3.3. Condition Reporting and the Condition Axis

Condition reports are the sole driver of an artwork's `condition_status`. A registrar files a report against an `artwork_id`, naming the `report_type` (`INTAKE`, `PRE_TRANSIT`, `POST_TRANSIT`, `PERIODIC`, or `LOAN_RETURN`), an assessed `condition_grade` on an `A` through `F` scale (`A`, `B`, `C`, `D`, or `F`), a `damage_noted` boolean, and optional free-text `notes`. The report is a permanent record and is never edited after filing.

The grade and the damage flag together may move the artwork along its condition axis. When a report notes damage (its `damage_noted` is true) and grades the work `C` or `D`, an artwork that was `SOUND` moves to `MINOR_DAMAGE`. When a report notes damage and grades the work `F`, an artwork that was `SOUND` or `MINOR_DAMAGE` moves to `MAJOR_DAMAGE`. Conversely, a clean re-inspection — a report grading the work `A` with `damage_noted` false — restores an artwork from `MINOR_DAMAGE` back to `SOUND`. Grades that do not match one of these patterns (for instance a `B`, or a `C`/`D` without damage noted) leave the condition axis unchanged.

Crossing into `MAJOR_DAMAGE` carries a protective cascade: the moment an artwork becomes `MAJOR_DAMAGE`, every loan agreement for that artwork currently in `APPROVED` or `ACTIVE` status is cancelled, transitioning to `CANCELLED`, and for each such cancelled loan any non-terminal carnet (one still in `ISSUED` or `ACTIVATED`) is discharged to `DISCHARGED`. This ensures a compromised work is never shipped or exhibited on the strength of paperwork approved before the damage was discovered.

### 3.4. Crating, Crews, and Transport

Moving a work safely begins with a crate. A `Coordinator` builds a crate for a specific `artwork_id`, choosing a `crate_type` (`SOFT`, `HARD`, or `CLIMATE`) and recording the interior dimensions `internal_length_cm`, `internal_width_cm`, and `internal_height_cm`. A crate starts `BUILDING`; the coordinator marks it `READY` when construction is complete. From `READY` it can be `RETIRED` (terminal). A crate that is being used on a live job sits at `IN_USE` and returns to `READY` when that job completes — those two transitions are system-driven by the transport job and are described below.

Rigging crews are the moving labor. A coordinator registers a crew with a `name`, a `crew_size`, and a `certification_level` (`STANDARD`, `FINE_ART`, or `MONUMENTAL`). A crew starts `AVAILABLE` and may be taken `OFFLINE`.

A transport job ties them together. A coordinator schedules a job naming the `artwork_id`, the `crate_id`, and the `crew_id`, an `origin_location` and `destination_location`, a `scheduled_start` and `scheduled_end`, a `requires_rigging` flag, and `estimated_hours` of labor. Scheduling is rejected when the window is malformed (`ERR_TIME_WINDOW_INVALID`) or when the crew is already committed in an overlapping window under the one-hour setup buffer described in Section 2.9 (`ERR_CREW_UNAVAILABLE`). The job is created `SCHEDULED`, and its `transport_charge_cents` is estimated up front: the estimated labor cost is `estimated_hours` multiplied by the crew hourly rate of 9,000 cents per hour, rounded half-up to whole cents, and then a flat rigging surcharge of 25,000 cents is added when `requires_rigging` is true (and nothing is added when it is false).

Starting the job advances it from `SCHEDULED` to `IN_PROGRESS`, but only when three conditions hold, evaluated in this order: the artwork's `condition_status` must not be `MAJOR_DAMAGE` (else `ERR_ARTWORK_CONDITION_UNSAFE`); the artwork's `custody_status` must be `IN_STORAGE` (else `ERR_ARTWORK_NOT_AVAILABLE`); and the named crate must be `READY` and built for that same artwork — its `crate_id` must reference a crate whose own artwork matches the job's `artwork_id` (else `ERR_CRATE_NOT_READY`). Starting the job cascades: the artwork's `custody_status` moves from `IN_STORAGE` to `IN_TRANSIT`, and the crate moves from `READY` to `IN_USE`.

Completing the job moves it from `IN_PROGRESS` to the terminal `COMPLETED` and requires `actual_hours` in the request; if `actual_hours` is absent the completion is rejected with `ERR_VALIDATION`. On completion the system records `actual_hours` and recomputes `transport_charge_cents` by the same rule as the estimate but substituting the logged `actual_hours` for the estimated hours (the rigging surcharge is applied identically). The cascade reverses the start: the artwork's `custody_status` returns from `IN_TRANSIT` to `IN_STORAGE`, and the crate returns from `IN_USE` to `READY`. Alternatively a `SCHEDULED` job may be `CANCELLED` (terminal), which releases the crew's reservation for that window.

### 3.5. Appraisal and Insurance

Before a work can be loaned it must be valued and covered, and both operations are guarded by the artwork-version concurrency control of Section 2.5. A registrar creates an appraisal against an `artwork_id`, choosing a `method` and supplying a `comparable_base_cents`, an `appraiser_name`, and the `expected_artwork_version`. Under the `FAIR_MARKET` method the appraised value equals `comparable_base_cents` outright, and the `replacement_multiplier` and `restoration_reserve_cents` inputs are ignored. Under the `REPLACEMENT` method the appraised value is `comparable_base_cents` multiplied by the `replacement_multiplier` (which defaults to 1.0), rounded half-up to whole cents, with the `restoration_reserve_cents` reserve (defaulting to 0) then added. The result is stored as the appraisal's `appraised_value_cents`. A new appraisal is created `FINALIZED`; any prior `FINALIZED` appraisal for the same artwork transitions to `SUPERSEDED`; and the artwork's own `appraised_value_cents` is set to the new value while its `version` is incremented by one — which is precisely the increment that a stale `expected_artwork_version` from a competing writer would fail to match.

Insurance follows the same superseding shape. A registrar creates a policy against an `artwork_id`, naming a `coverage_type` (`STORAGE_ONLY`, `TRANSIT`, or `ALL_RISK`), the declared `insured_value_cents`, an `effective_start` and `effective_end`, and the `expected_artwork_version`. The premium is computed with a single final rounding after all factors combine. First a rate in basis points is selected from the insured value: 200 basis points when `insured_value_cents` is at most 500,000, otherwise 150 basis points when it is at most 5,000,000, otherwise 100 basis points. The base annual figure is `insured_value_cents` multiplied by that rate and divided by 10,000. That figure is then scaled by the coverage multiplier — 1.0 for `STORAGE_ONLY`, 1.5 for `TRANSIT`, 2.0 for `ALL_RISK` — by the artwork's fragility multiplier — 1.0 for `LOW`, 1.25 for `MEDIUM`, 1.5 for `HIGH` — and by the coverage duration expressed as a fraction of a year, namely the exact elapsed time from `effective_start` to `effective_end` measured in days — its total seconds divided by 86,400, keeping any fractional day rather than rounding up — then divided by 365. The scaled amount is rounded half-up to whole cents, and the stored `premium_cents` is the greater of that rounded amount and the floor premium of 5,000 cents. A new policy is created `ACTIVE`; any prior `ACTIVE` policy for the artwork transitions to `SUPERSEDED`; the artwork's `active_policy_id` is set to the new policy and its `version` is incremented by one.

An `Approver` may cancel an `ACTIVE` policy, moving it to `CANCELLED`; if that policy was the artwork's current coverage, the artwork's `active_policy_id` is cleared. A policy is also lapsed automatically by the system when a loan activation finds its coverage past `effective_end` (see Section 3.6): the policy transitions from `ACTIVE` to `LAPSED` and, if it was the artwork's current coverage, `active_policy_id` is cleared. The four policy states are `ACTIVE`, `CANCELLED`, `SUPERSEDED`, and `LAPSED`.

### 3.6. Loans, Certificates of Authenticity, and Customs Carnets

A loan agreement carries an artwork out to an exhibition, and its lifecycle is deliberately cyclic to accommodate revision. A registrar drafts a loan naming the `artwork_id`, the lending `client_id`, the `borrower_name`, the `exhibition_name`, a `loan_start` and `loan_end`, an `is_international` flag, and the `required_value_cents` of coverage the borrower demands. The loan is created `DRAFT` with `coa_issued` false and no `coa_number`. The registrar submits it, moving `DRAFT` to `SUBMITTED`; submission records `submitted_by_user_id` as the submitting caller's `X-User-ID`. A submitted loan can be sent back to `DRAFT` for revision and resubmitted any number of times — this is the revision loop.

Approval is an `Approver` action from `SUBMITTED` to `APPROVED`, and it is the most heavily guarded transition in the system. Its checks run in this order: first, segregation of duties — the approver's `X-User-ID` must differ from the recorded `submitted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; then the artwork's `condition_status` must not be `MAJOR_DAMAGE`, else `ERR_ARTWORK_CONDITION_UNSAFE`; then the artwork's `custody_status` must be `IN_STORAGE`, else `ERR_ARTWORK_NOT_AVAILABLE`; then the artwork must have at least one `FINALIZED` appraisal, else `ERR_NO_FINALIZED_APPRAISAL`; and finally the artwork must have an `ACTIVE` insurance policy whose `insured_value_cents` is at least the loan's `required_value_cents`, else `ERR_INSUFFICIENT_COVERAGE`. On approval the loan issues a certificate of authenticity: `coa_issued` is set true and a `coa_number` serial is assigned. A submitted loan may instead be `REJECTED` by an approver (terminal), and an `APPROVED` loan may be `CANCELLED` by an approver, which discharges the loan's carnet if it is still in `ISSUED` or `ACTIVATED`.

Activation is a `Coordinator` action from `APPROVED` to `ACTIVE`, and it is where the piece physically leaves for exhibition. Activation requires that the artwork's `custody_status` is still `IN_STORAGE` (else `ERR_ARTWORK_NOT_AVAILABLE`); that the artwork has an `ACTIVE` policy that is not past its `effective_end` — if there is no active policy the activation is rejected with `ERR_POLICY_NOT_ACTIVE`, and if a policy exists but has run past its `effective_end` the system lapses that policy to `LAPSED` and rejects with `ERR_POLICY_EXPIRED`; and, when the loan is international (`is_international` true), that a carnet for the loan exists in `ISSUED` status whose `validity_end` is on or after the current clock — a missing issued carnet is rejected with `ERR_CARNET_REQUIRED`, and an issued carnet whose validity has already passed is rejected with `ERR_CARNET_EXPIRED`. On successful activation the artwork's `custody_status` moves from `IN_STORAGE` to `ON_LOAN`; as a cascade its `ACTIVE` storage placement is suspended, moving that placement to `SUSPENDED` and decrementing the vault's `occupied_slots` by one; and for an international loan the loan's carnet moves from `ISSUED` to `ACTIVATED`.

Returning the work is a coordinator action from `ACTIVE` to the terminal `RETURNED`. It reverses the custody cascade: the artwork's `custody_status` moves from `ON_LOAN` back to `IN_STORAGE`, its suspended placement is reactivated — moving that placement from `SUSPENDED` to `ACTIVE` and incrementing the vault's `occupied_slots` by one (subject to the vault still having a free slot, else `ERR_VAULT_FULL`) — and the loan's carnet, if it is in `ISSUED` or `ACTIVATED`, is discharged to `DISCHARGED`. The full loan lifecycle spans `DRAFT`, `SUBMITTED`, `APPROVED`, `REJECTED`, `ACTIVE`, `RETURNED`, and `CANCELLED`.

Carnets are the customs instrument for cross-border loans. A coordinator issues a carnet against a `loan_id`, recording its `carnet_number`, the array of `countries` (ISO country codes) it covers, and its `validity_start` and `validity_end`. A carnet starts `ISSUED`. It is activated to `ACTIVATED` by the system when its owning international loan activates, and discharged to `DISCHARGED` either by the system when the owning loan returns or is cancelled, or directly by a coordinator; a coordinator's direct discharge is permitted only from `ACTIVATED` (a still-`ISSUED` carnet cannot be discharged directly — it may only be expired). A still-issued carnet may be expired to `EXPIRED` by a coordinator, but only once its `validity_end` is earlier than the current clock; otherwise the expiry is rejected with `ERR_INVALID_STATE`. `DISCHARGED` and `EXPIRED` are terminal.

### 3.7. Private Viewings

Collectors and prospective buyers view works in dedicated rooms. A coordinator creates a viewing room with a `name` and a `capacity_persons`, and it starts `OPERATIONAL`; the coordinator may `CLOSED` it and reopen it to `OPERATIONAL`. A viewing booking is requested by a `Client` for its own work, or by a `Coordinator` on a client's behalf, naming the `artwork_id`, the `viewing_room_id`, the requesting `client_id`, and a `scheduled_start` and `scheduled_end`. A booking is created `REQUESTED`.

A coordinator confirms a booking, moving it from `REQUESTED` to `CONFIRMED`, subject to three checks in order: the artwork's `condition_status` must not be `MAJOR_DAMAGE` (else `ERR_ARTWORK_CONDITION_UNSAFE`); the room must be `OPERATIONAL` (else `ERR_ROOM_NOT_OPERATIONAL`); and the requested window must not half-open overlap any other `CONFIRMED` booking on the same room, per the no-buffer rule of Section 2.9 (else `ERR_ROOM_UNAVAILABLE`). A confirmed booking may then be `COMPLETED`, marked `NO_SHOW`, or `CANCELLED`; a still-requested booking may be `CANCELLED` outright. `COMPLETED`, `CANCELLED`, and `NO_SHOW` are terminal.

### 3.8. Billing and the Client Ledger

Billing gathers a period's chargeable events into an invoice. A `BillingAdmin` generates an invoice for a `client_id` over a `billing_period_start` to `billing_period_end`, optionally attaching `manual_line_items`. The system builds the invoice's `line_items` — each an entry of a `description` and an `amount_cents` — by auto-aggregating, for that client and period, the `final_fee_cents` of every `RELEASED` storage placement whose `released_at` falls within the inclusive `[billing_period_start, billing_period_end]` window and the `transport_charge_cents` of every `COMPLETED` transport job whose `scheduled_end` falls within that same inclusive window, together with any supplied `manual_line_items`; the assembled `line_items` are ordered as released placements first, then completed transport jobs, then the manual line items, each group in creation order. The invoice is created `DRAFT`.

Totals are computed with a pinned rounding order. The `subtotal_cents` is the sum of the whole-cent `amount_cents` of every line item. The `tax_cents` is the subtotal multiplied by the tax rate of 8.75 percent, rounded half-up to whole cents once, on the summed subtotal — tax is never computed or rounded per line item. The `total_cents` is `subtotal_cents` plus `tax_cents`.

An invoice moves through `DRAFT`, `ISSUED`, `PAID`, and `VOID`. Issuing a draft moves it to `ISSUED` and increments the billed client's `outstanding_balance_cents` by the invoice's `total_cents`. Paying an issued invoice moves it to `PAID` and decrements the client's `outstanding_balance_cents` by the same `total_cents`. Voiding an issued invoice moves it to `VOID` and likewise decrements the balance by `total_cents`, a compensating action that restores the ledger; a `DRAFT` invoice may also be voided directly, and because it was never issued that void makes no balance adjustment. Throughout, a client's `outstanding_balance_cents` equals the sum of `total_cents` over that client's invoices currently in `ISSUED` status — the ledger is conserved under issue, pay, and void.

## 4. Endpoint Definitions

All endpoints share the response envelope of Section 2.2. Creating a new resource returns HTTP 201; reads and state modifications return HTTP 200. The request and response bodies for each endpoint are not restated here — reconstruct them from the workflow narratives of Section 3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Registrar, Coordinator, Approver, BillingAdmin |
| POST | `/clients` | Register a client / owner | Registrar |
| GET | `/clients/{id}` | Get a client | Registrar, Client |
| GET | `/clients` | List clients | Registrar |
| POST | `/clients/{id}/state` | Suspend / reactivate a client | Registrar |
| POST | `/vaults` | Create a climate vault | Registrar |
| GET | `/vaults/{id}` | Get a vault | Registrar, Coordinator, Approver |
| GET | `/vaults` | List vaults | Registrar, Coordinator, Approver |
| POST | `/vaults/{id}/state` | Transition vault status | Registrar |
| POST | `/artworks` | Intake an artwork | Registrar |
| GET | `/artworks/{id}` | Get an artwork | Registrar, Coordinator, Approver, Client |
| GET | `/artworks` | List artworks | Registrar, Coordinator, Approver, Client |
| POST | `/artworks/{id}/state` | Deaccession an artwork | Registrar |
| POST | `/condition-reports` | File a condition report | Registrar |
| GET | `/condition-reports/{id}` | Get a condition report | Registrar, Coordinator |
| GET | `/condition-reports` | List condition reports | Registrar, Coordinator |
| POST | `/appraisals` | Create a FINALIZED appraisal (OCC on artwork version) | Registrar |
| GET | `/appraisals/{id}` | Get an appraisal | Registrar, Approver |
| GET | `/appraisals` | List appraisals | Registrar, Approver |
| POST | `/policies` | Create an ACTIVE policy (OCC on artwork version) | Registrar |
| POST | `/policies/{id}/state` | Cancel a policy | Approver |
| GET | `/policies/{id}` | Get a policy | Registrar, Approver |
| GET | `/policies` | List policies | Registrar, Approver |
| POST | `/crates` | Build a crate for an artwork | Coordinator |
| POST | `/crates/{id}/state` | Transition crate status | Coordinator |
| GET | `/crates/{id}` | Get a crate | Coordinator, Registrar |
| GET | `/crates` | List crates | Coordinator, Registrar |
| POST | `/crews` | Register a rigging crew | Coordinator |
| GET | `/crews/{id}` | Get a crew | Coordinator |
| GET | `/crews` | List crews | Coordinator |
| POST | `/transport-jobs` | Schedule a transport job | Coordinator |
| POST | `/transport-jobs/{id}/state` | Transition a transport job | Coordinator |
| GET | `/transport-jobs/{id}` | Get a transport job | Coordinator, Registrar |
| GET | `/transport-jobs` | List transport jobs | Coordinator, Registrar |
| POST | `/storage-placements` | Place an artwork in a vault | Registrar |
| POST | `/storage-placements/{id}/state` | Release a placement | Registrar |
| GET | `/storage-placements/{id}` | Get a placement | Registrar, Coordinator |
| GET | `/storage-placements` | List placements | Registrar, Coordinator |
| POST | `/loans` | Draft a loan agreement | Registrar |
| POST | `/loans/{id}/state` | Transition a loan | Registrar, Approver, Coordinator |
| GET | `/loans/{id}` | Get a loan | Registrar, Approver, Coordinator, Client |
| GET | `/loans` | List loans | Registrar, Approver, Coordinator, Client |
| POST | `/carnets` | Issue an ATA carnet for a loan | Coordinator |
| POST | `/carnets/{id}/state` | Transition carnet status | Coordinator |
| GET | `/carnets/{id}` | Get a carnet | Coordinator |
| GET | `/carnets` | List carnets | Coordinator |
| POST | `/viewing-rooms` | Create a viewing room | Coordinator |
| POST | `/viewing-rooms/{id}/state` | Open / close a viewing room | Coordinator |
| GET | `/viewing-rooms/{id}` | Get a viewing room | Coordinator, Client |
| GET | `/viewing-rooms` | List viewing rooms | Coordinator, Client |
| POST | `/viewing-bookings` | Request a private viewing | Client, Coordinator |
| POST | `/viewing-bookings/{id}/state` | Confirm / complete / cancel / no-show a booking | Coordinator |
| GET | `/viewing-bookings/{id}` | Get a booking | Coordinator, Client |
| GET | `/viewing-bookings` | List bookings | Coordinator, Client |
| POST | `/invoices` | Generate a DRAFT invoice | BillingAdmin |
| POST | `/invoices/{id}/state` | Issue / pay / void an invoice | BillingAdmin |
| GET | `/invoices/{id}` | Get an invoice | BillingAdmin, Client |
| GET | `/invoices` | List invoices | BillingAdmin, Client |

## 5. Error Code Catalogue

The trigger conditions for each error are defined in the narratives of Sections 2 and 3.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_OWNERSHIP_REQUIRED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_TIME_WINDOW_INVALID` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_ARTWORK_CONDITION_UNSAFE` | 422 |
| `ERR_ARTWORK_NOT_AVAILABLE` | 409 |
| `ERR_CRATE_NOT_READY` | 409 |
| `ERR_CLIMATE_MISMATCH` | 422 |
| `ERR_NO_FINALIZED_APPRAISAL` | 422 |
| `ERR_POLICY_NOT_ACTIVE` | 409 |
| `ERR_POLICY_EXPIRED` | 409 |
| `ERR_CARNET_REQUIRED` | 422 |
| `ERR_CARNET_EXPIRED` | 409 |
| `ERR_CREW_UNAVAILABLE` | 409 |
| `ERR_ROOM_UNAVAILABLE` | 409 |
| `ERR_ROOM_NOT_OPERATIONAL` | 409 |
| `ERR_VAULT_UNAVAILABLE` | 409 |
| `ERR_VAULT_FULL` | 409 |
| `ERR_INSUFFICIENT_COVERAGE` | 422 |
</content>
</invoke>
