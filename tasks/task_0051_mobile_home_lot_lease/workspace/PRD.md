# Mobile Home Lot Lease API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Mobile Home Lot Lease API, a back-office platform for operating manufactured-housing communities where residents own their homes but rent the land beneath them. The land-lease relationship creates a distinctive set of business problems: a single master utility bill must be fairly split across many occupied lots, rent increases are bounded by state-specific statutory caps, a home sale transfers occupancy of a lot without disturbing the rent that rides with the land, and a community may convert from park ownership to resident ownership only through a quorum vote of its occupants.

The API models the full operational lifecycle of a community — its lots, residents, leases, rent schedules, utility apportionment, eviction proceedings, and ownership-conversion votes — under a regime of immediate consistency where every charge, payment, and state change is reflected the moment it is recorded. Three classes of actor interact with the system: the park operator who administers the community, the residents who act on their own tenancies, and a state housing auditor who reads but never writes. The sections below define the global contracts every endpoint shares, the business rules that govern each workflow, the complete endpoint surface, and the catalogue of error conditions.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the principal's operational capacity. If `X-User-Role` is missing or does not name a recognized role, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the header is present and recognized but the named role is not permitted to perform the requested operation under the access matrix, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly three roles: `ParkManager`, `Resident`, and `HousingAuthority`.

A `ParkManager` is the community operator. When `X-User-Role` is `ParkManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but does not compare it to any entity's `id`. The `ParkManager` administers communities, lots, residents, leases, rent schedules, utility billing, evictions, and conversion votes.

A `Resident` acts on their own tenancy — accepting or contesting rent increases, curing eviction notices, posting payments, and casting conversion ballots. When `X-User-Role` is `Resident`, `X-User-ID` is the `id` of the acting `Resident` entity; ownership checks on any resource that references a `Resident` compare the resource's resident foreign key to `X-User-ID`.

A `HousingAuthority` is a read-only state compliance auditor that verifies caps, cure periods, and apportionment conservation. When `X-User-Role` is `HousingAuthority`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. A `HousingAuthority` may invoke any GET endpoint and nothing else.

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

---

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most primary resources — `Community`, `Lot`, `Resident`, `LotLease`, `RentSchedule`, `UtilityBill`, `EvictionCase`, and `ConversionVote` — carry a standard set of system-managed fields:

- **`id`** — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at`** — an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was first created.
- **`updated_at`** — an ISO 8601 UTC timestamp recording the most recent modification, refreshed on every change to the resource.
- **`version`** — a system-managed integer that begins at creation and increments by one with every modification. It underpins optimistic concurrency control where applicable.

Four entities are append-only or immutable records and therefore carry only `id` and `created_at`, with no `updated_at` and no `version`: `UtilityReading` (an append-only sub-meter reading), `UtilityCharge` (an immutable apportionment line item), `ConversionBallot` (one immutable ballot per lot per vote), and `LotLedgerEntry` (an append-only ledger row). For these four, neither `updated_at` nor `version` is present.

### 2.5. Hierarchical Consistency and Derived-State Propagation

Many operations mutate more than one resource at once, and the system applies all such cascades immediately and atomically. Whenever a lot's lifecycle state changes — occupancy, eviction, freeze, or unfreeze — the lot's `version` increments by one and its `updated_at` refreshes. When a rent schedule becomes effective, when an eviction notice is served, cured, adjudicated, or dismissed, and when a conversion vote freezes or unfreezes lots, each affected lot independently has its `version` incremented and `updated_at` refreshed.

Several fields are derived and recomputed rather than supplied by the client. A community's `occupied_lot_count` is the number of its lots in `OCCUPIED` status; it rises by one when a lot becomes occupied and falls by one when an occupied lot is vacated by eviction. A lot's `current_rent_cents` is the `new_rent_cents` of the lot's currently effective rent schedule, falling back to the lot's `base_rent_cents` when no schedule is yet effective. A resident's `arrears_cents` is recomputed on every ledger post. A community's `total_metered_units` is recomputed for each apportionment run. These derived values are always returned in their current computed form on the relevant GET endpoints.

### 2.6. Nested Resource Retrieval and Referential Integrity

Resource identifiers supplied in a request path or body are validated left-to-right. The first identifier that does not resolve to an existing resource causes immediate rejection with `ERR_NOT_FOUND` (HTTP 404), before any later identifier or business rule is evaluated. All required body fields must be present and well-typed, and any enum-valued field must carry a value from its permitted set; a violation yields `ERR_INVALID_REQUEST` (HTTP 400). These checks apply to every POST and PATCH request.

Because the topology is flat and peer entities reference one another by foreign key, the system enforces a community-scoping rule: when creating a lease, a utility bill, or a conversion ballot, the referenced lot, resident, and lease must all belong to the same community. A cross-community reference is rejected with `ERR_CROSS_COMMUNITY_REFERENCE` (HTTP 409).

### 2.7. Optimistic Concurrency on Lot Occupancy

A single concurrency-controlled operation exists in the system: activating a home-sale successor lease against a lot. When a lease activation carries a `supersedes_lease_id` (the home-sale supersede path), the activation request must include `expected_lot_version` carrying the `version` of the target `Lot` that the client last observed. The server compares `expected_lot_version` against the lot's current `version`. If another writer has advanced the lot's version since the client read it — for example, a prior successor lease already activated, or a rent schedule went effective and bumped the lot version — the values differ and the activation is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412). This guards against a client overwriting an occupancy change it never observed. First-occupancy activations (those without a `supersedes_lease_id`) do not require `expected_lot_version`; no other endpoint takes a version field.

### 2.8. Precision, Rounding, and Conservation

All monetary amounts are stored and returned as integer cents; no fractional cent ever survives a calculation. Utility apportionment uses a largest-remainder distribution so that the apportioned shares sum exactly to the master charge. Rent-cap arithmetic floors the cap ceiling to a whole cent before comparison. Arrears are aggregated in integer cents and floored at zero so the figure is never negative. The precise mechanics of each calculation appear with the workflow that triggers it.

### 2.9. The Test-Driving Clock

Several eviction rules are time-sensitive, turning on whether the current moment falls on, before, or after a derived deadline. To make these deterministic, the server maintains a logical current UTC instant. An administrative test-driving capability sets that instant to a supplied `to_iso8601` value, after which all cure-period and adjudication-window evaluations use the new instant. This capability is restricted to the `ParkManager` role.

## 3. Business Logic & Workflows

### 3.1. Communities and the Lot Inventory

A community is the light scoping parent for everything else. A `ParkManager` creates a community by supplying a `name` and a `state_code`, optionally choosing the `utility_apportionment_method`. The `state_code` is one of `CA`, `OR`, `FL`, or `TX`, and it selects the annual rent-increase cap regime described in §3.4. The `utility_apportionment_method` is either `PER_CAPITA` or `SUB_METER`, defaulting to `PER_CAPITA` when omitted; it governs how a master utility charge is divided, as detailed in §3.5. At creation the community's `ownership_model` is set to `PARK_OWNED` and its `occupied_lot_count` starts at zero. The `ownership_model` can later become `RESIDENT_OWNED`, but only through a passed conversion vote (§3.7). A community's `total_metered_units` is the sum of metered consumption across the readings being apportioned and is recomputed per apportionment run.

Within a community a `ParkManager` creates lots. A lot is created with its parent `community_id`, a `lot_number`, and a `base_rent_cents` (the monthly base lot rent in cents, which anchors the lot's first rent schedule). The `lot_number` is a human-readable label that must be unique within its community; a duplicate is rejected with `ERR_DUPLICATE_LOT_NUMBER` (HTTP 409). A newly created lot begins in `VACANT` status with `current_lease_id` null and `current_rent_cents` equal to `base_rent_cents`. Over its life a lot's `status` moves among `VACANT`, `OCCUPIED`, `EVICTING`, and `FROZEN`; the `FROZEN` state blocks new leases while a community conversion vote is open. The lot's `current_lease_id` points to the `LotLease` currently occupying it, or is null while the lot is `VACANT`.

The `ParkManager` also registers residents. A resident is created with a `community_id`, a `full_name`, and a `household_size`, where `household_size` is the number of occupants in the household and must be at least 1. The household size feeds per-capita utility weighting. A new resident starts with `standing` of `GOOD` and `arrears_cents` of zero. A resident's `standing` is one of `GOOD`, `DELINQUENT`, or `EVICTED`.

### 3.2. Leasing a Lot: First Occupancy

A lease binds a resident to a lot. A `ParkManager` creates a lease by supplying the `lot_id`, the `resident_id`, and a `start_date` (the ISO date the term begins). A first-occupancy lease leaves `supersedes_lease_id` null; the home-sale path that sets it is covered in §3.3. A freshly created lease is `PENDING`. Its `status` ranges over `PENDING`, `ACTIVE`, `TERMINATED`, and `TRANSFERRED`, where `TRANSFERRED` denotes a lease superseded by a home-sale successor. The `rent_cents_at_signing` field captures the lot's `current_rent_cents` at activation.

Activation by a `ParkManager` is the pivotal step. To activate a first-occupancy lease the lease must be `PENDING`; otherwise the request fails with `ERR_INVALID_STATE` (HTTP 409). The target lot must be `VACANT`; a non-vacant lot is rejected with `ERR_LOT_NOT_VACANT` (HTTP 409). The lot must not be `FROZEN` by an open conversion vote; a frozen lot is rejected with `ERR_LOT_FROZEN` (HTTP 409). When these hold, the lot transitions `VACANT → OCCUPIED`, the lot's `current_lease_id` is set to this lease, the lease transitions `PENDING → ACTIVE`, the lease's `rent_cents_at_signing` is snapshotted from the lot's `current_rent_cents`, the community's `occupied_lot_count` increases by one, and the lot's `version` increments by one. As part of activation, a first `RENT_CHARGE` ledger entry equal to `rent_cents_at_signing` is posted against the resident's lease.

### 3.3. Home Sale: Supersede Activation

When a resident sells their manufactured home, the buyer takes over the lot's lease rather than starting a fresh tenancy, and the rent rides with the lot, not with the departing home. To model this, a `ParkManager` creates a successor lease whose `supersedes_lease_id` names the lease currently occupying the lot, and includes `expected_lot_version` carrying the lot's last observed `version`. Activating that successor lease drives the supersede path.

For supersede activation the lot must be `OCCUPIED` and the supplied `supersedes_lease_id` must equal the lot's `current_lease_id`; a mismatch is rejected with `ERR_INVALID_STATE` (HTTP 409). The lease being activated must itself be `PENDING`, and the prior lease named must be the lot's current `ACTIVE` lease. The supersede is blocked when an eviction case is open on the lot's prior lease, in which case the request is rejected with `ERR_EVICTION_IN_PROGRESS` (HTTP 409). The supplied `expected_lot_version` must match the lot's current `version`; if it does not, the request is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412), as described in §2.7. When all conditions hold, the prior lease transitions `ACTIVE → TRANSFERRED`, the successor lease transitions `PENDING → ACTIVE` with its `rent_cents_at_signing` snapshotted from the lot's `current_rent_cents`, the lot's `current_lease_id` is repointed to the successor lease, and the lot's `version` increments by one. The lot remains `OCCUPIED` throughout (an `OCCUPIED → OCCUPIED` transition), so the community's `occupied_lot_count` is unchanged.

### 3.4. Rent Increases Under State Caps

Rent on a lot is raised through a rent schedule, and the same workflow exists to keep increases inside each state's statutory ceiling. A `ParkManager` proposes an increase by supplying the `lot_id`, a `proposed_rent_cents`, and an `effective_date` (the ISO date the new rent takes effect). At proposal the system snapshots the lot's `current_rent_cents` into the schedule's `prior_rent_cents` — this is the baseline against which the cap is measured — and immediately computes the schedule's `new_rent_cents` and `cap_applied` flag. A newly proposed schedule is `PROPOSED`; its `status` ranges over `PROPOSED`, `ACCEPTED`, `CONTESTED`, `EFFECTIVE`, and `WITHDRAWN`.

The cap computation works against the community's `state_code`. Each capped state has a maximum annual increase fraction: California permits at most 5 percent, Oregon at most 7 percent, and Florida at most 10 percent. Texas has no statutory cap. For a capped state, the maximum allowed rent is `prior_rent_cents` multiplied by one plus that state's fraction, with the product floored to a whole cent; the legally effective `new_rent_cents` is then the smaller of `proposed_rent_cents` and that floored maximum. For Texas, the maximum allowed equals `proposed_rent_cents` itself, so the effective `new_rent_cents` is simply the proposed amount and the cap never binds. The `cap_applied` flag is true exactly when `proposed_rent_cents` is strictly greater than the maximum allowed — meaning the proposal was reduced — and is therefore always false in Texas.

A schedule moves through a branching accept-or-contest cycle. The `Resident` may accept the proposal, taking it from `PROPOSED → ACCEPTED`, or contest it, taking it from `PROPOSED → CONTESTED`; each transition requires the schedule to be `PROPOSED` and otherwise fails with `ERR_INVALID_STATE`. When a proposal is `CONTESTED`, the `ParkManager` may revise it by supplying a new `proposed_rent_cents`; revision requires the schedule to be `CONTESTED`, recomputes `new_rent_cents` and `cap_applied` against the same `prior_rent_cents` and `effective_date` baseline, and returns the schedule to `PROPOSED` so the resident may respond again. The `ParkManager` may withdraw a `PROPOSED` schedule, taking it `PROPOSED → WITHDRAWN`; withdrawal requires the schedule to be `PROPOSED`.

Applying an accepted schedule makes it effective. Application requires the schedule to be `ACCEPTED`, failing otherwise with `ERR_INVALID_STATE`. It also requires that the schedule's `effective_date` fall at least 12 months after the `effective_date` of the lot's most recent already-effective schedule; an `effective_date` that is less than 12 months after that prior effective date is rejected with `ERR_INCREASE_TOO_SOON` (HTTP 409). On success the schedule transitions `ACCEPTED → EFFECTIVE`, the lot's `current_rent_cents` recomputes to the schedule's `new_rent_cents`, and the lot's `version` increments by one.

### 3.5. Utility Apportionment

A community periodically receives a master-meter utility bill that must be split fairly across its occupied lots. A `ParkManager` creates a utility bill with the `community_id`, a `utility_type` (one of `WATER`, `ELECTRIC`, or `SEWER`), a `period_start` (the inclusive ISO start of the billing period), a `period_end` (the exclusive ISO end), and a `master_charge_cents` (the total master-meter charge to apportion). A new bill is `DRAFT`; once apportioned it becomes `APPORTIONED`. Its computed `apportioned_total_cents` is the sum of all generated charge amounts and must equal `master_charge_cents`.

Under `SUB_METER` apportionment the manager attaches sub-meter readings to a draft bill, each reading supplying a `lot_id` and the `metered_units` consumed by that lot in the period. Readings carry a `utility_bill_id` linking them to their bill and are append-only.

Running apportionment moves the bill `DRAFT → APPORTIONED`. It requires the bill to be `DRAFT` (otherwise `ERR_INVALID_STATE`) and the community to have at least one `OCCUPIED` lot; with zero occupied lots the run is rejected with `ERR_NO_OCCUPIED_LOTS` (HTTP 409). Under `SUB_METER` the summed metered consumption across the bill's readings must be greater than zero; if it is zero the run is rejected with `ERR_NO_METER_READINGS` (HTTP 409).

The apportionment distributes `master_charge_cents` across the set of currently `OCCUPIED` lots in the community, each of which must have an active lease. The lots are ordered by their `created_at` ascending, with `lot_number` ascending as a stable tie-break. Each lot receives a weight. Under the `PER_CAPITA` variant (the default) a lot's weight is the `household_size` of the resident on the lot's active lease, and meter readings are ignored entirely. Under the `SUB_METER` variant a lot's weight is the sum of that lot's `metered_units` for this bill, and household size is ignored entirely. The total weight is the sum of weights across the occupied set, and each lot's raw share is `master_charge_cents` multiplied by that lot's weight divided by the total weight.

Because raw shares are fractional, the system uses a largest-remainder distribution to land exactly on the master charge. First each lot's raw share is floored to whole cents. The leftover remainder — `master_charge_cents` minus the sum of the floors — is then distributed one cent at a time to lots in descending order of their fractional remainder, with ties broken by `created_at` ascending. This guarantees the apportioned shares sum to exactly `master_charge_cents`. For each occupied lot the run creates one immutable `UtilityCharge` recording its `utility_bill_id`, `lot_id`, `resident_id` (the resident on the lot's active lease at apportionment time), and `amount_cents` (its apportioned share). For each charge a corresponding `UTILITY_CHARGE` ledger entry is posted against that lot's active resident, and the bill's `apportioned_total_cents` is set to the conserved sum.

### 3.6. The Lease Ledger, Arrears, and Payments

Every financial event on a lease is recorded as an immutable ledger entry. A `LotLedgerEntry` carries the `lease_id`, the `resident_id`, an `entry_type` of `RENT_CHARGE`, `UTILITY_CHARGE`, or `PAYMENT`, and a signed `amount_cents` that is positive for charges and negative for payments. Lease activation posts the opening `RENT_CHARGE`, apportionment posts `UTILITY_CHARGE` rows, and payments post negative `PAYMENT` rows.

A payment is posted against a lease by either a `ParkManager` or the `Resident`, supplying the payment's `amount_cents`. Posting a payment writes a negative `PAYMENT` ledger entry and recomputes the resident's arrears. A resident's `arrears_cents` is the sum of the signed amounts of all ledger entries on that resident's active lease, with the result floored at zero so it is never negative; entries belonging to prior `TRANSFERRED` or `TERMINATED` leases are excluded. Arrears are recomputed on every ledger post — charge or payment alike. A payment that brings arrears below the nonpayment threshold may restore a delinquent resident's standing to `GOOD`, as described in §3.7.

### 3.7. Eviction: Notice, Cure, and Adjudication

Eviction is a branching cure-or-evict proceeding. A `ParkManager` serves a notice by creating an eviction case with the `lease_id` and a `reason` of either `NONPAYMENT` or `LEASE_VIOLATION`. A `NONPAYMENT` notice may be served only when the resident's `arrears_cents` is at least 50000 cents — that is, five hundred dollars — at notice time; serving a nonpayment notice below that threshold is rejected with `ERR_ARREARS_BELOW_THRESHOLD` (HTTP 409). A `LEASE_VIOLATION` notice documents a rule breach and carries no arrears precondition. Serving a notice requires the lot to be `OCCUPIED`; otherwise the request fails with `ERR_INVALID_STATE`. A new case begins in `NOTICE_SERVED`; its `status` ranges over `NOTICE_SERVED`, `CURED`, `ADJUDICATED`, and `DISMISSED`.

Serving the notice cascades: the case's `cure_deadline` is derived, the lot transitions `OCCUPIED → EVICTING`, the lot's `version` increments by one, and for a nonpayment reason the resident's `standing` becomes `DELINQUENT`. The `cure_deadline` is computed from the notice date — the date portion of the case's `created_at` — plus a state-specific number of days, then taken at the end of that day: California allows 60 days, Oregon allows 30 days, Florida allows 30 days, and Texas allows 14 days. The deadline is the inclusive boundary that separates the cure window from the adjudication window.

A `Resident` may cure the case. Curing requires the case to be `NOTICE_SERVED`, and the current instant must be on or before the `cure_deadline`; a cure attempted strictly after the deadline is rejected with `ERR_CURE_PERIOD_EXPIRED` (HTTP 409). For a `NONPAYMENT` case, curing additionally requires that a posted payment has brought arrears below the threshold of 50000 cents; if arrears remain at or above the threshold the cure is rejected with `ERR_ARREARS_NOT_CLEARED` (HTTP 409). A successful cure moves the case `NOTICE_SERVED → CURED`, returns the lot `EVICTING → OCCUPIED`, restores the resident's `standing` from `DELINQUENT` to `GOOD`, and increments the lot's `version` by one.

A `ParkManager` may adjudicate to uphold the eviction. Adjudication requires the case to be `NOTICE_SERVED`, and the current instant must be strictly after the `cure_deadline`; an adjudication attempted on or before the deadline is rejected with `ERR_CURE_PERIOD_ACTIVE` (HTTP 409). Upholding moves the case `NOTICE_SERVED → ADJUDICATED` and cascades the lot from `EVICTING → VACANT`: the lease transitions `ACTIVE → TERMINATED`, the lot's `current_lease_id` is cleared to null, the resident's `standing` becomes `EVICTED`, the community's `occupied_lot_count` decreases by one, and the lot's `version` increments by one. Alternatively a `ParkManager` may dismiss a `NOTICE_SERVED` case, moving it `NOTICE_SERVED → DISMISSED` and returning the lot `EVICTING → OCCUPIED` with its `version` incremented; dismissal requires the case to be `NOTICE_SERVED`.

### 3.8. Park-to-Resident Ownership Conversion

A community may convert from park ownership to resident ownership through a quorum vote of its occupants. A `ParkManager` creates a conversion vote with the `community_id` and a `quorum_threshold_pct` — a fraction strictly greater than 0 and at most 1, naming the share of eligible lots whose ballots must be YES for the conversion to pass. A new vote is `OPEN`; its `status` ranges over `OPEN`, `PASSED`, and `FAILED`. The vote carries a computed `yes_count` (the number of YES ballots, starting at zero) and an `eligible_lot_count` snapshotted when balloting opens.

Opening balloting snapshots the vote's `eligible_lot_count` to the community's current `occupied_lot_count` — the fixed denominator for the quorum test — and freezes the community's lots: every `OCCUPIED` lot transitions `OCCUPIED → FROZEN` and has its `version` incremented by one. While a lot is `FROZEN` no new lease may be activated on it.

Either a `ParkManager` or a `Resident` casts a ballot for the vote by supplying the `lot_id` and a `choice` of `YES` or `NO`. There may be only one ballot per lot per vote, and the lot must be occupied and therefore eligible; a second ballot for the same lot, or a ballot for an ineligible lot, is rejected with `ERR_DUPLICATE_BALLOT` (HTTP 409). A ballot records its `conversion_vote_id`, `lot_id`, and `choice`, and casting one recomputes the vote's `yes_count`.

Tallying resolves the vote. The quorum test compares `yes_count` divided by `eligible_lot_count` against `quorum_threshold_pct`: when the ratio is at least the threshold the vote passes, and when the ratio is below the threshold it fails — falling short of quorum routes to a `FAILED` outcome rather than an error. Tallying requires the vote to be `OPEN`, otherwise `ERR_INVALID_STATE`. On a passing tally the vote moves `OPEN → PASSED`, the community's `ownership_model` flips `PARK_OWNED → RESIDENT_OWNED`, and every frozen community lot transitions `FROZEN → OCCUPIED` with its `version` incremented. On a failing tally the vote moves `OPEN → FAILED`, the community's `ownership_model` is left unchanged, and the same unfreeze cascade returns every frozen lot `FROZEN → OCCUPIED` with its `version` incremented.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including state transitions and apportionment runs — return a `200 OK` status code. All write operations are restricted to the roles shown; every GET endpoint is available to `ParkManager`, `Resident`, and `HousingAuthority`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/communities` | Create a community | ParkManager |
| GET | `/communities/{id}` | Get a community | ParkManager, Resident, HousingAuthority |
| POST | `/lots` | Create a lot in a community | ParkManager |
| GET | `/lots/{id}` | Get a lot | ParkManager, Resident, HousingAuthority |
| GET | `/lots` | List lots, filterable by community or current lease | ParkManager, Resident, HousingAuthority |
| POST | `/residents` | Register a resident | ParkManager |
| GET | `/residents/{id}` | Get a resident | ParkManager, Resident, HousingAuthority |
| GET | `/residents` | List residents, filterable by community | ParkManager, Resident, HousingAuthority |
| POST | `/lot-leases` | Create a PENDING lease (optionally a home-sale supersede) | ParkManager |
| GET | `/lot-leases/{id}` | Get a lease | ParkManager, Resident, HousingAuthority |
| GET | `/lot-leases` | List leases, filterable by lot or resident | ParkManager, Resident, HousingAuthority |
| POST | `/lot-leases/{id}/activate` | Activate a lease, occupying or superseding on the lot | ParkManager |
| POST | `/lot-leases/{id}/payments` | Post a payment against a lease ledger | ParkManager, Resident |
| POST | `/rent-schedules` | Propose a rent increase for a lot | ParkManager |
| GET | `/rent-schedules/{id}` | Get a rent schedule | ParkManager, Resident, HousingAuthority |
| GET | `/rent-schedules` | List rent schedules, filterable by lot | ParkManager, Resident, HousingAuthority |
| POST | `/rent-schedules/{id}/accept` | Resident accepts the proposed increase | Resident |
| POST | `/rent-schedules/{id}/contest` | Resident contests the proposed increase | Resident |
| POST | `/rent-schedules/{id}/revise` | Manager revises a contested proposal | ParkManager |
| POST | `/rent-schedules/{id}/apply` | Apply an accepted schedule, making it effective | ParkManager |
| POST | `/rent-schedules/{id}/withdraw` | Manager withdraws a proposed schedule | ParkManager |
| POST | `/utility-bills` | Create a DRAFT utility master bill | ParkManager |
| GET | `/utility-bills/{id}` | Get a utility bill | ParkManager, Resident, HousingAuthority |
| GET | `/utility-bills` | List utility bills, filterable by community | ParkManager, Resident, HousingAuthority |
| POST | `/utility-bills/{id}/readings` | Attach a sub-meter reading to a draft bill | ParkManager |
| GET | `/utility-readings/{id}` | Get a single sub-meter reading | ParkManager, Resident, HousingAuthority |
| GET | `/utility-readings` | List sub-meter readings, filterable by bill or lot | ParkManager, Resident, HousingAuthority |
| POST | `/utility-bills/{id}/apportion` | Run apportionment across occupied lots | ParkManager |
| GET | `/utility-charges/{id}` | Get a single apportioned charge | ParkManager, Resident, HousingAuthority |
| GET | `/utility-charges` | List apportioned charges, filterable by bill, lot, or resident | ParkManager, Resident, HousingAuthority |
| GET | `/lot-ledger-entries/{id}` | Get a single ledger entry | ParkManager, Resident, HousingAuthority |
| GET | `/lot-ledger-entries` | List ledger entries, filterable by lease or resident | ParkManager, Resident, HousingAuthority |
| POST | `/eviction-cases` | Serve an eviction notice on a lease | ParkManager |
| GET | `/eviction-cases/{id}` | Get an eviction case | ParkManager, Resident, HousingAuthority |
| GET | `/eviction-cases` | List eviction cases, filterable by lease | ParkManager, Resident, HousingAuthority |
| POST | `/eviction-cases/{id}/cure` | Resident cures within the cure period | Resident |
| POST | `/eviction-cases/{id}/adjudicate` | Uphold eviction after the cure period lapses | ParkManager |
| POST | `/eviction-cases/{id}/dismiss` | Manager dismisses the eviction | ParkManager |
| POST | `/conversion-votes` | Create a conversion vote | ParkManager |
| GET | `/conversion-votes/{id}` | Get a conversion vote | ParkManager, Resident, HousingAuthority |
| GET | `/conversion-votes` | List conversion votes, filterable by community | ParkManager, Resident, HousingAuthority |
| POST | `/conversion-votes/{id}/open` | Open balloting, snapshot eligibility, freeze lots | ParkManager |
| POST | `/conversion-votes/{id}/ballots` | Cast one ballot for an occupied lot | ParkManager, Resident |
| GET | `/conversion-votes/{id}/ballots` | List ballots for a vote | ParkManager, Resident, HousingAuthority |
| GET | `/conversion-ballots/{id}` | Get a single ballot | ParkManager, Resident, HousingAuthority |
| GET | `/conversion-ballots` | List ballots, filterable by vote or lot | ParkManager, Resident, HousingAuthority |
| POST | `/conversion-votes/{id}/tally` | Tally ballots, resolve by quorum, unfreeze lots | ParkManager |
| POST | `/_clock/set_current_utc` | Set the server's current UTC instant (test-driving) | ParkManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_CROSS_COMMUNITY_REFERENCE` | 409 |
| `ERR_DUPLICATE_LOT_NUMBER` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_LOT_NOT_VACANT` | 409 |
| `ERR_LOT_FROZEN` | 409 |
| `ERR_EVICTION_IN_PROGRESS` | 409 |
| `ERR_STALE_LOT_VERSION` | 412 |
| `ERR_INCREASE_TOO_SOON` | 409 |
| `ERR_CURE_PERIOD_EXPIRED` | 409 |
| `ERR_CURE_PERIOD_ACTIVE` | 409 |
| `ERR_ARREARS_BELOW_THRESHOLD` | 409 |
| `ERR_ARREARS_NOT_CLEARED` | 409 |
| `ERR_NO_OCCUPIED_LOTS` | 409 |
| `ERR_NO_METER_READINGS` | 409 |
| `ERR_DUPLICATE_BALLOT` | 409 |
