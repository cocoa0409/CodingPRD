# Urban Forestry & Tree Permit API — Product Requirements Document

## 1. Introduction

Municipal urban-forestry programs sit at the intersection of public-safety liability, ecological policy, and regulated construction work. A single street tree may be a protected heritage specimen, a canopy-coverage asset counted against a neighborhood's greening target, a candidate for removal under a homeowner's permit, and — after a windstorm — an emergency hazard that must come down before an 811 utility locate has even cleared. This API is the system of record that ties those concerns together: a public-tree inventory with GIS coordinates and canopy accounting, a protected-tree removal and pruning permit workflow with mitigation fees and replacement obligations, a contractor work-order and 811 dig-ticket coordination layer, a storm-emergency track, and a condition-inspection and risk-rating pipeline whose results feed both the permit gate and the zone's high-risk tally.

The system is designed for six non-overlapping operational roles — administrators, field staff, arborists, inspectors, public applicants, and licensed contractors — each owning a distinct slice of the lifecycle. Its defining challenge is consistency under cascade: finalizing an inspection can change a tree's health and a zone's risk count; completing a removal work order can retire a tree, close a permit, and recompute a zone's canopy percentage; disputing an inspection must precisely undo what its finalization did. Every such cascade is immediate and atomic within the request that triggers it. Monetary mitigation is tracked to the whole cent, canopy to two decimal places, and every timing decision — dig windows, license expiry, storm windows — is judged against a server-controlled logical clock rather than wall-clock time, so that the entire regulated sequence is deterministic and auditable.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and contracts that apply across the entire API. The API is mounted under `/forestry`.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares their operational capacity. If either header is missing, or if `X-User-Role` does not name a known role, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are valid but the named role is not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly six roles: `ForestryAdmin`, `ForestryStaff`, `Arborist`, `Inspector`, `Applicant`, and `Contractor`. All six may perform any read (GET) operation. Write operations are partitioned among them without overlap: a `ForestryAdmin` manages reference data (zones, species, contractors), declares and closes storm events, records 811 clearance, revokes permits, disputes inspections, and controls the logical clock; a `ForestryStaff` member manages the tree inventory, schedules and aborts work orders, and marks replacement plantings as planted; an `Arborist` reviews and issues permits; an `Inspector` creates condition inspections, finalizes their risk ratings, and establishes replacement plantings; an `Applicant` files permits and drives them through submit, provide-info, and fee payment; a `Contractor` starts and completes the work orders assigned to it and requests dig tickets.

Five of the six roles carry an opaque identity. When `X-User-Role` is `ForestryAdmin`, `ForestryStaff`, `Arborist`, `Inspector`, or `Applicant`, the `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server does not compare it to any entity's `id`. For the `Applicant` role there is one place the server records that opaque identifier: when a permit is filed, the acting `X-User-ID` is stored on the permit as `requested_by_user_id`, and later ownership checks compare the acting `Applicant`'s `X-User-ID` against that stored value rather than against any entity id. The `Contractor` role is different: when `X-User-Role` is `Contractor`, the `X-User-ID` is the `id` of the acting `Contractor` entity, and ownership checks on any work order compare the work order's `contractor_id` foreign key against `X-User-ID`. In both cases an ownership violation is reported as `ERR_NOT_OWNER` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, all list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Most resources carry a standard set of system-managed fields. Every resource has an `id`, a server-minted UUID with no type prefix, and a `created_at` timestamp, an ISO 8601 UTC instant with three fractional digits recording when the resource was first created. Resources that can be mutated after creation additionally carry an `updated_at` timestamp — refreshed on every change — and an integer `version` that begins at its initial value and increments by one on each mutation. This applies to `Zone`, `Tree`, `Inspection`, `Permit`, `Contractor`, `WorkOrder`, `DigTicket`, `StormEvent`, and `ReplacementPlanting`.

The one exception is `Species`, which is immutable configuration data: a species record carries only `id` and `created_at`. It has neither an `updated_at` field nor a `version` field, and none should be emitted for it.

Whenever the server updates a derived field on a resource as part of a cascade — for example recomputing a zone's canopy figures or its risk count — that update is itself a mutation of the affected resource: its `updated_at` is refreshed and its `version` is incremented, even though no client submitted a direct change to that resource.

### 2.5. Nested Resource Retrieval and Validation Ordering

Two resource families are reached through a parent path: a tree's inspections are addressed beneath the tree, and a work order's dig tickets are addressed beneath the work order. When a path names more than one resource, existence is validated strictly left to right, and the first identifier that does not resolve produces the corresponding not-found error before any deeper resource is consulted — a request for the inspections of a non-existent tree yields `ERR_TREE_NOT_FOUND`, never `ERR_INSPECTION_NOT_FOUND`.

More generally, the server evaluates every request through a fixed priority ladder, and the earliest failing rung determines the error returned. Authentication is checked first (`ERR_UNAUTHENTICATED`, 401), then role authorization (`ERR_UNAUTHORIZED`, 403), then existence of every resource named by a path segment (a `ERR_<RESOURCE>_NOT_FOUND` at 404). Ownership is checked next for the operations that require it (`ERR_NOT_OWNER`, 403). Then the request body is validated for shape — required fields present and correctly typed (`ERR_INVALID_REQUEST`, 400) — followed by enum validity, where any enum-valued field carrying a value outside its declared set is rejected with `ERR_INVALID_ENUM` (422). Foreign keys carried in the body are then resolved (`zone_id`, `species_id`, `tree_id`, `permit_id`, `contractor_id`, `affected_zone_id`, `work_order_id`), and an unresolved reference yields the matching not-found error at 404. The concrete not-found code corresponds to the missing resource in each case: `ERR_ZONE_NOT_FOUND` for a zone, `ERR_SPECIES_NOT_FOUND` for a species, `ERR_TREE_NOT_FOUND` for a tree, `ERR_INSPECTION_NOT_FOUND` for an inspection, `ERR_PERMIT_NOT_FOUND` for a permit, `ERR_REPLACEMENT_NOT_FOUND` for a replacement planting, `ERR_CONTRACTOR_NOT_FOUND` for a contractor, `ERR_WORK_ORDER_NOT_FOUND` for a work order, `ERR_DIG_TICKET_NOT_FOUND` for a dig ticket, and `ERR_STORM_EVENT_NOT_FOUND` for a storm event. Only after all of that does the server evaluate state-machine legality (`ERR_INVALID_STATE`, 409), the optimistic-concurrency check (`ERR_STALE_VERSION`, 412), and finally the domain-specific business rules described throughout §3. Where two business rules could both fire on one request, the specific ordering is called out in the workflow narrative below.

### 2.6. Precision, Rounding, and Monetary Units

All rounding in this system uses the round-half-up convention. Canopy percentages are rounded to exactly two decimal places. Monetary mitigation is tracked in whole integer cents — `mitigation_fee_cents`, `fee_paid_cents`, and the fee amounts submitted for payment are all integer cent counts, never fractional dollars. Where a fee is derived from a dollar-denominated input, the conversion to cents multiplies by 100 and the half-up rounding to a whole cent is applied at the point specified for each fee variant in §3; risk scores and replacement counts are exact integers with no rounding.

### 2.7. Optimistic Concurrency Control on Inspection Creation

Creating a condition inspection for a tree is guarded by optimistic concurrency control. The create request must carry `expected_tree_version`, a non-optional field holding the `version` of the target `Tree` that the client last observed. Because inspections are periodic, the server bumps the tree's `version` each time an inspection is created and records the new inspection as the tree's current one; consequently, if another writer has created an inspection against the same tree since the client last read it, the client's `expected_tree_version` will no longer match the tree's current `version`. When `expected_tree_version` does not equal the tree's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from superseding an inspection it never saw. No other endpoint takes a version field; only inspection creation is OCC-guarded.

### 2.8. The Logical Clock

All time-sensitive decisions — dig-ticket window validity, contractor license expiry, storm-event windows, and lazy dig-ticket expiration — are evaluated against a server-controlled logical clock, never against wall-clock time. At startup the clock reads exactly `2026-03-01T00:00:00Z`, and until an administrator advances it the clock stays fixed at that default rather than drifting to real time. An administrator-only test-driving capability sets the clock to a supplied `to_iso8601` instant. All license, dig-window, and storm-window comparisons in §3 refer to "the clock" or "now" in the sense of this logical value.

### 2.9. Canopy Accounting and the Conserved Mitigation Invariant

A zone's canopy figures are a maintained aggregate, never client-supplied. The zone's `live_canopy_sqm` is the sum of the mature canopy area (`mature_canopy_sqm` of each tree's species) over all trees standing in the zone whose `health_status` is `HEALTHY`, `DECLINING`, or `HAZARD` — that is, every tree that has not been removed — plus the mature canopy area of every `ReplacementPlanting` whose `target_zone_id` is this zone and whose `status` is `ESTABLISHED`. From that, `current_canopy_pct` is `live_canopy_sqm` divided by the zone's `area_sqm`, multiplied by 100, and rounded half-up to two decimal places. The `canopy_status` is `MEETS` when `current_canopy_pct` is greater than or equal to the zone's `target_canopy_pct`, and `DEFICIT` otherwise (the boundary at exactly the target counts as `MEETS`). These three fields are recomputed together whenever a tree is added to the zone, whenever a removal work order completes, and whenever a replacement planting is established. A zone additionally maintains `tree_count`, the number of its trees whose `health_status` is not `REMOVED`, and `high_risk_tree_count`, the number of its trees whose `risk_rating` is `HIGH` or `SEVERE`.

Mitigation obligations are governed by a conserved system-wide accounting quantity: the total outstanding mitigation, expressed in cents. Approving a removal permit adds that permit's `mitigation_fee_cents` to the outstanding total; closing the permit (when its removal work is completed) subtracts the same amount; and revoking the permit subtracts it as a compensating action. The invariant is that each approved permit contributes its fee exactly once while it is live and nothing once it is closed or revoked — closing already subtracts the contribution, so a revoke after a close does not subtract it a second time.

### 2.10. Cascade and Compensation Consistency

Several operations mutate more than one entity atomically within the triggering request, and every such cascade has a precisely defined inverse where the domain allows reversal. Finalizing an inspection writes the tree's risk and health and then recomputes the owning zone's high-risk count; disputing that same inspection restores the tree's prior risk and health from snapshots taken at finalize time and recomputes the zone's count back to its pre-finalize value. Completing a removal work order retires the tree, recomputes the zone's canopy and counts, and closes the authorizing permit. Establishing a replacement planting adds canopy to its target zone. In each case the secondary and tertiary effects are as much part of the operation as the primary state change, and each mutated resource has its `updated_at` and `version` advanced per §2.4.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Zones, Species, and Contractors

The forestry program is scaffolded by three kinds of reference data that a `ForestryAdmin` establishes before operational work begins. A **Zone** models a management zone or neighborhood and is created with a `name`, a `target_canopy_pct` (a canopy-coverage goal, as a percentage between 0 and 100 inclusive), and an `area_sqm` (total land area in square metres, which must be greater than zero and serves as the denominator for canopy percentage). At creation the zone's derived accounting starts empty: `live_canopy_sqm` is 0, `current_canopy_pct` is 0, `canopy_status` is `DEFICIT`, and both `tree_count` and `high_risk_tree_count` are 0.

A **Species** is immutable configuration describing one kind of tree. It carries a common `name`, an `is_protected_species` flag (true for heritage or protected species that require a permit to remove regardless of trunk size), an `is_native` flag, a `mature_canopy_sqm` giving the canopy area one mature tree of the species contributes (at least 0), a `base_replacement_value_dollars` (the nominal per-tree nursery replacement value in dollars, at least 0, used by the replacement-cost mitigation method), a `base_appraisal_value_per_sqin` (a trunk-formula unit appraisal value in dollars per square inch of basal area, at least 0, used by the appraised-value mitigation method), and a `min_spacing_m` (the minimum planting spacing in metres for the species, at least 0).

A **Contractor** is a licensed tree-service company, registered with a `name`, a municipal `license_number`, a `license_expiry` (an ISO 8601 UTC instant), an `is_certified_arborist` flag indicating an ISA arborist certification, and an operational `status` of `ACTIVE` or `SUSPENDED`. Status may be set at registration and defaults to `ACTIVE`, so system initialization is permitted to produce a `SUSPENDED` contractor. A `SUSPENDED` contractor cannot be assigned to work, as detailed in §3.6.

### 3.2. Tree Inventory, GIS, and Protected Classification

A `ForestryStaff` member adds a public tree to the inventory by supplying its `zone_id`, its `species_id`, a `dbh_inches` (diameter at breast height in inches, which must be greater than zero and drives protected classification, the replacement-count tier, and appraised value), a `canopy_radius_m` (observed canopy radius in metres, at least 0), a GIS `latitude` and `longitude`, and a field `condition_class` of `GOOD`, `FAIR`, `POOR`, or `DEAD`.

At creation the tree's `is_protected` flag is computed once and treated as an immutable snapshot: a tree is protected when its `dbh_inches` is at least 8.0 inches, or when its species has `is_protected_species` set to true. The 8.0-inch boundary is inclusive — a tree measured at exactly 8.0 inches is protected. A newly inventoried tree begins with `health_status` of `HEALTHY`, `risk_rating` of `NONE`, and its risk and health snapshots (`prior_risk_rating`, `prior_health_status`) likewise at `NONE` and `HEALTHY`; its `current_inspection_id` is null until a first inspection exists. Adding the tree recomputes the owning zone's `live_canopy_sqm`, `current_canopy_pct`, `canopy_status`, and `tree_count` per §2.9.

Trees can be listed and filtered by `zone_id`, by `species_id`, by `health_status`, and by `is_protected`; the tree list, like all lists, is paginated with `limit` and `offset`. A tree's own record can be fetched directly by id.

### 3.3. Condition Inspection and Risk Rating

Inspections drive a tree's risk and health lifecycle. An `Inspector` creates a **condition inspection** against a tree, subject to the optimistic-concurrency guard of §2.7 (the `expected_tree_version` field). The inspection is created with an `inspection_type` of `ROUTINE`, `RISK`, or `POST_STORM`, and three integer field ratings each between 1 and 4: a `likelihood_score` (likelihood of failure, 1 improbable to 4 probable), a `consequence_score` (consequence of failure, 1 negligible to 4 severe), and a `target_rating` (occupancy of the failure zone, 1 rare to 4 constant). A new inspection begins in `DRAFT` status.

The system uses a shared band table to map an integer risk score to a rating: a score of 3 or less is `LOW`; a score from 4 through 7 is `MODERATE`; a score from 8 through 11 is `HIGH`; and a score of 12 or more is `SEVERE`. Each lower boundary is inclusive. At create time the server computes the **provisional** variant and stores it on the inspection: `provisional_risk_score` is the `likelihood_score` multiplied by the `consequence_score`, with no target bonus and no cap, and `provisional_risk_rating` is that score's band. Creating the inspection also records it as the tree's `current_inspection_id` and increments the tree's `version` by one.

When the `Inspector` **finalizes** an inspection — a transition permitted only from `DRAFT` or from `DISPUTED` status, and rejected with `ERR_INVALID_STATE` otherwise — the server computes the **final** variant. The `final_risk_score` is the `likelihood_score` multiplied by the `consequence_score`, plus a target bonus of 3 when the `target_rating` is 3 or greater (and no bonus when it is below 3), with the resulting sum then capped at a maximum of 16; that is, the final score is the smaller of the bonus-adjusted product and 16. The `final_risk_rating` is that final score's band. Both remain null until the inspection reaches `FINALIZED`. Because the target bonus can lift the score into a higher band than the provisional rating, the final rating may exceed the provisional one.

Finalizing cascades onto the tree and its zone atomically. First the server snapshots the tree's current `risk_rating` into `prior_risk_rating` and its current `health_status` into `prior_health_status`, so a later dispute can restore them deterministically. It then sets the tree's `risk_rating` to the `final_risk_rating`. It sets the tree's `health_status` to `HAZARD` when the final rating is `SEVERE`, to `DECLINING` when the final rating is `HIGH`, and to `HEALTHY` otherwise (that is, when the final rating is `LOW` or `MODERATE`). Finally it recomputes the owning zone's `high_risk_tree_count`, since a rating of `HIGH` or `SEVERE` places the tree in the high-risk set. The inspection moves `DRAFT → FINALIZED` (or `DISPUTED → FINALIZED` when re-finalized after a dispute).

A `ForestryAdmin` may **dispute** a finalized inspection, transitioning it `FINALIZED → DISPUTED`. A dispute is allowed only when the inspection is currently `FINALIZED` and when it is the tree's latest inspection — that is, the tree's `current_inspection_id` equals this inspection's id; a dispute of any earlier inspection, or of one not in `FINALIZED`, is rejected with `ERR_INVALID_STATE`. Disputing compensates the finalize exactly: it restores the tree's `risk_rating` from `prior_risk_rating` and its `health_status` from `prior_health_status`, then recomputes the zone's `high_risk_tree_count` so the count returns to its pre-finalize value. Because finalize and dispute form a loop, a single inspection may cycle between `FINALIZED` and `DISPUTED` any number of times, each finalize re-snapshotting and each dispute restoring. An inspection can be fetched by id, and a tree's inspections can be listed beneath it.

### 3.4. The Protected-Tree Permit Lifecycle

An `Applicant` files a **permit** for a tree by supplying the `tree_id`, a `permit_type` of `REMOVAL` or `PRUNING`, and a free-text `reason`. The server records the acting `X-User-ID` as the permit's `requested_by_user_id` and starts the permit in `DRAFT`. The permit moves through the states `DRAFT`, `UNDER_REVIEW`, `INFO_REQUESTED`, `APPROVED`, `DENIED`, `ISSUED`, `CLOSED`, and `REVOKED`, of which `DENIED`, `CLOSED`, and `REVOKED` are terminal.

The owning `Applicant` **submits** the permit, transitioning `DRAFT → UNDER_REVIEW`. Submit requires that the acting `Applicant`'s `X-User-ID` equal the permit's `requested_by_user_id` (otherwise `ERR_NOT_OWNER`), and it enforces the protected-tree rule: the governed tree's `is_protected` must be true, because only a protected tree requires a permit. Submitting a permit for a non-protected tree is rejected with `ERR_TREE_NOT_PROTECTED` (422).

An `Arborist` **reviews** an `UNDER_REVIEW` permit, supplying a `decision` of `APPROVE`, `DENY`, or `REQUEST_INFO`, and may attach `review_notes`. A `DENY` decision moves the permit to `DENIED`; a `REQUEST_INFO` decision moves it to `INFO_REQUESTED`. From `INFO_REQUESTED`, the owning `Applicant` responds through the provide-info step (optionally attaching a `response_note`), which returns the permit `INFO_REQUESTED → UNDER_REVIEW`; provide-info also enforces the same ownership check as submit. A permit may cycle between `UNDER_REVIEW` and `INFO_REQUESTED` any number of times before a terminal decision.

An `APPROVE` decision moves the permit `UNDER_REVIEW → APPROVED` and is the point at which mitigation is computed. For a `REMOVAL` permit, approval has two preconditions: the tree's `current_inspection_id` must reference an inspection whose status is `FINALIZED` (otherwise `ERR_INSPECTION_REQUIRED`, 422), and the request must carry a `mitigation_method` of either `REPLACEMENT_COST` or `APPRAISED_VALUE`, which selects the fee formula. For a `PRUNING` permit, `mitigation_method` is ignored and forced to null. The side effects of approving are detailed in §3.5.

Before an approved permit can be issued, its fee must be paid. The owning `Applicant` **pays the fee** by submitting an `amount_cents` value, which must exactly equal the permit's `mitigation_fee_cents`; a mismatch is rejected with `ERR_FEE_AMOUNT_MISMATCH` (422). A successful payment sets `fee_paid` to true and records `fee_paid_cents` as the amount paid. Pay-fee is subject to the same `Applicant` ownership check as submit and provide-info.

An `Arborist` **issues** an approved, paid permit, moving it `APPROVED → ISSUED`. Issuance has two guards evaluated in a fixed order: the state precondition — the permit must be in `APPROVED` — is checked first and outranks the fiscal precondition. If the permit is not in `APPROVED`, issuance fails with `ERR_PERMIT_NOT_APPROVED` (409) regardless of payment; only once the permit is confirmed `APPROVED` does the server check that `fee_paid` is true, failing with `ERR_FEE_UNPAID` (402) when it is not.

A `ForestryAdmin` may **revoke** a permit that is in `APPROVED` or in `ISSUED`, moving it to `REVOKED` and optionally attaching a `reason`. Revocation subtracts the permit's `mitigation_fee_cents` from the outstanding mitigation total as a compensating action for the approve-time debit — but only if that amount had not already been subtracted when the permit closed. Any replacement-planting rows created at approval are not deleted, but because the permit is now `REVOKED` they no longer count toward outstanding mitigation. Separately, a permit reaches `CLOSED` from `ISSUED` automatically when its removal or pruning work order completes, as described in §3.6. Permits can be fetched by id and listed or filtered by `tree_id` and by `status`.

### 3.5. Mitigation: Replacement Count, Fee, and Replacement Plantings

Approving a `REMOVAL` permit computes two conserved quantities and instantiates the replacement obligation, all atomically. The `required_replacement_count` is tiered by the governed tree's `dbh_inches` with inclusive lower bounds: a tree under 8.0 inches requires 0 replacements (it is protected, if at all, only by species, and carries no size-based replacement); a tree from 8.0 up to but not including 18.0 inches requires 1; a tree from 18.0 up to but not including 30.0 inches requires 2; and a tree of 30.0 inches or more requires 3. A `PRUNING` permit never incurs mitigation: its `required_replacement_count` is 0 and its `mitigation_fee_cents` is 0.

The `mitigation_fee_cents` is computed at approval by the variant that `mitigation_method` selects. Under the `REPLACEMENT_COST` method, the server first computes the per-tree cost in cents by taking the species' `base_replacement_value_dollars`, multiplying by the replacement site factor of 1.075, and multiplying by 100 to convert dollars to cents, then rounding that per-tree result half-up to a whole number of cents; the fee is that rounded per-tree cent amount multiplied by the `required_replacement_count`. The rounding must be applied to each tree individually before multiplying by the count — the unrounded per-tree dollar figures must not be summed and rounded once. Under the `APPRAISED_VALUE` method, the fee follows the trunk formula and is independent of the replacement count: the basal trunk area in square inches is 0.5454 multiplied by the square of the tree's `dbh_inches`; a condition factor is selected from the tree's `condition_class` — 1.0 for `GOOD`, 0.75 for `FAIR`, 0.5 for `POOR`, and 0.25 for `DEAD`; and the fee is the species' `base_appraisal_value_per_sqin` multiplied by that trunk area, multiplied by the condition factor, multiplied by 100, with a single half-up rounding to a whole number of cents applied at the very end. Approval adds the resulting `mitigation_fee_cents` to the outstanding mitigation total described in §2.9.

Approval of a `REMOVAL` permit also creates `required_replacement_count` **replacement planting** rows, each in status `REQUIRED`. Each planting defaults its `species_id` to the removed tree's species and its `target_zone_id` to the removed tree's zone, and carries a 1-based `sequence_index` from 1 through the count (its ordinal within the permit's required set). Each planting is linked to its originating removal permit by `permit_id`.

A replacement planting progresses through `REQUIRED`, `PLANTED`, and `ESTABLISHED`. A `ForestryStaff` member marks a required planting as **planted** (`REQUIRED → PLANTED`), which is allowed only when the planting is currently `REQUIRED` and its parent permit's `status` is one of `APPROVED`, `ISSUED`, or `CLOSED` — not `REVOKED` or `DENIED`. An `Inspector` then **establishes** a planted one (`PLANTED → ESTABLISHED`), allowed only from `PLANTED`; establishing adds the planting species' `mature_canopy_sqm` to the `live_canopy_sqm` of its `target_zone_id` and recomputes that zone's `current_canopy_pct` and `canopy_status`. Both transitions are rejected with `ERR_INVALID_STATE` when attempted from the wrong status. Plantings can be fetched by id, listed beneath their permit, and listed or filtered globally by `permit_id`, `species_id`, `target_zone_id`, and `status`.

### 3.6. Work Orders, 811 Dig Tickets, and Contractor Scheduling

A `ForestryStaff` member creates a **work order** to authorize physical tree work. The request supplies the subject `tree_id`, the assigned `contractor_id`, a `work_type`, a `scheduled_start`, and a `scheduled_end`, and — for normal work — a `permit_id`. The scheduled window is half-open: `scheduled_end` must be strictly after `scheduled_start`. The `work_type` is `REMOVAL`, `PRUNING`, or `EMERGENCY_REMOVAL`, and it determines how the work is authorized. A `REMOVAL` or `PRUNING` work order requires its `permit_id` to reference a permit in `ISSUED`; a permit in any other state causes `ERR_PERMIT_NOT_ISSUED` (409). An `EMERGENCY_REMOVAL` work order instead requires `permit_id` to be null and an `ACTIVE` storm event covering the tree's zone at the current clock; absent that declaration the create is rejected with `ERR_EMERGENCY_NOT_DECLARED` (422). A new work order begins in `CREATED`.

Two scheduling guards apply at creation. The assigned contractor must be `ACTIVE`; assigning a `SUSPENDED` contractor is rejected with `ERR_CONTRACTOR_LICENSE_EXPIRED` (422). And the contractor must not be double-booked: the new work order's half-open window from `scheduled_start` up to `scheduled_end` must not overlap the window of any other work order for the same contractor that is currently in `CREATED` or `IN_PROGRESS`. Because the intervals are half-open, two windows that merely touch at an endpoint — one ending exactly where the next begins — do not overlap; a genuine overlap is rejected with `ERR_CONTRACTOR_DOUBLE_BOOKED` (409).

Before work can start, a `Contractor` requests an **811 dig ticket** beneath the work order, supplying a `ticket_number`, a `valid_from`, and a `valid_to`. The lawful dig window is half-open: `valid_from` is inclusive, `valid_to` is exclusive and must be strictly after `valid_from`, otherwise the create is rejected with `ERR_DIG_WINDOW_INVALID` (422). Requesting a dig ticket is an ownership-checked operation — the acting `Contractor`'s `X-User-ID` must equal the work order's `contractor_id`, else `ERR_NOT_OWNER`. A new ticket begins in `REQUESTED`. A `ForestryAdmin` records 811 utility clearance, moving the ticket `REQUESTED → VALID`. A ticket lazily expires: whenever it is read or consulted at start time, if the logical clock has reached `valid_to` (that is, now is at or past `valid_to`), the ticket becomes `EXPIRED`, whether it was `REQUESTED` or `VALID`.

The assigned `Contractor` **starts** the work order (`CREATED → IN_PROGRESS`). Start is ownership-checked against `contractor_id`, and then enforces two business preconditions in a fixed priority order: the dig-ticket safety check outranks the license referential check. The server first requires that some dig ticket for this work order be `VALID` and in-window — its window must contain the clock, meaning `valid_from` at or before now and now strictly before `valid_to`; if no such ticket exists the start fails with `ERR_DIG_TICKET_INVALID` (409). Only once a valid in-window ticket is confirmed does the server require the contractor to be `ACTIVE` with an unexpired license — the logical clock strictly before `license_expiry` — failing with `ERR_CONTRACTOR_LICENSE_EXPIRED` (422) if the license has expired.

The assigned `Contractor` **completes** the work order (`IN_PROGRESS → COMPLETED`), also ownership-checked. Completion cascades according to the work type. When the `work_type` is `REMOVAL` or `EMERGENCY_REMOVAL`, the subject tree's `health_status` is set to `REMOVED`, which in turn recomputes the owning zone's `live_canopy_sqm`, `current_canopy_pct`, `canopy_status`, `tree_count`, and `high_risk_tree_count`. When the work order carries a non-null `permit_id`, completion transitions that permit `ISSUED → CLOSED` and subtracts its `mitigation_fee_cents` from the outstanding mitigation total. Alternatively, a `ForestryStaff` member may **abort** a work order from either `CREATED` or `IN_PROGRESS` (optionally with a `reason`), moving it to `ABORTED`; an abort fires no removal side effects — no tree or canopy changes — and simply frees the contractor's scheduled window. `CREATED`, `IN_PROGRESS`, `COMPLETED`, and `ABORTED` are the work-order states, with `COMPLETED` and `ABORTED` terminal. Work orders can be fetched by id, listed beneath a work order for their dig tickets, and listed or filtered by `tree_id`, `permit_id`, `contractor_id`, and `status`. Dig tickets can also be fetched directly by id.

### 3.7. Storm Events and Emergency Removal

A `ForestryAdmin` declares a **storm event** over a zone by supplying the `affected_zone_id`, a `severity` of `MINOR`, `MAJOR`, or `SEVERE`, a `window_start`, and a `window_end`. The emergency window is a closed interval: both `window_start` and `window_end` are inclusive, and `window_end` must be strictly after `window_start`. A new event begins `ACTIVE`. Two active storm events may not overlap on the same zone, and because the interval is closed, two windows that touch at an endpoint do overlap — an overlapping declaration on a zone already under an `ACTIVE` event is rejected with `ERR_STORM_OVERLAP` (409). An administrator **closes** an active event (`ACTIVE → CLOSED`), after which the zone no longer authorizes new `EMERGENCY_REMOVAL` work orders. Storm events can be fetched by id and listed or filtered by `affected_zone_id` and by `status`.

An `EMERGENCY_REMOVAL` work order, as noted in §3.6, is authorized not by a permit but by an `ACTIVE` storm event whose window contains the current clock and whose zone matches the subject tree's zone. This is the emergency path: a hazard tree can be removed under a declared storm without waiting for the full permit lifecycle, and its completion still cascades the tree to `REMOVED` and recomputes the zone's canopy and counts exactly as a permitted removal would, but with no permit to close.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; operations that modify an existing resource, including state-transition actions and the logical-clock control, return `200 OK`. All GET reads are available to every role. The complete request and response semantics for each endpoint are given by the workflow narratives in §3; the table below lists only the HTTP surface.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/forestry/zones` | Create a management zone | ForestryAdmin |
| GET | `/forestry/zones/{id}` | Fetch a zone with its derived canopy fields | All roles |
| POST | `/forestry/species` | Create a species record | ForestryAdmin |
| GET | `/forestry/species/{id}` | Fetch a species | All roles |
| POST | `/forestry/trees` | Add a public tree to the inventory | ForestryStaff |
| GET | `/forestry/trees/{id}` | Fetch a tree | All roles |
| GET | `/forestry/trees` | List/filter trees | All roles |
| POST | `/forestry/trees/{id}/inspections` | Create a condition inspection (OCC-guarded) | Inspector |
| GET | `/forestry/trees/{id}/inspections` | List inspections for a tree | All roles |
| GET | `/forestry/inspections/{id}` | Fetch an inspection | All roles |
| POST | `/forestry/inspections/{id}/finalize` | Finalize an inspection; cascade to tree and zone | Inspector |
| POST | `/forestry/inspections/{id}/dispute` | Dispute the latest finalized inspection | ForestryAdmin |
| POST | `/forestry/permits` | File a permit for a protected tree | Applicant |
| GET | `/forestry/permits/{id}` | Fetch a permit | All roles |
| GET | `/forestry/permits` | List/filter permits | All roles |
| POST | `/forestry/permits/{id}/submit` | Submit a DRAFT permit for review | Applicant |
| POST | `/forestry/permits/{id}/review` | Arborist decision: APPROVE / DENY / REQUEST_INFO | Arborist |
| POST | `/forestry/permits/{id}/provide-info` | Respond to an info request | Applicant |
| POST | `/forestry/permits/{id}/pay-fee` | Pay the mitigation fee | Applicant |
| POST | `/forestry/permits/{id}/issue` | Issue an approved, fee-paid permit | Arborist |
| POST | `/forestry/permits/{id}/revoke` | Revoke an approved or issued permit | ForestryAdmin |
| GET | `/forestry/permits/{id}/replacement-plantings` | List a permit's replacement plantings | All roles |
| GET | `/forestry/replacement-plantings/{id}` | Fetch a replacement planting | All roles |
| GET | `/forestry/replacement-plantings` | List/filter replacement plantings | All roles |
| POST | `/forestry/replacement-plantings/{id}/plant` | Mark a required replacement as planted | ForestryStaff |
| POST | `/forestry/replacement-plantings/{id}/establish` | Confirm a planted replacement has established | Inspector |
| POST | `/forestry/contractors` | Register a licensed contractor | ForestryAdmin |
| GET | `/forestry/contractors/{id}` | Fetch a contractor | All roles |
| POST | `/forestry/work-orders` | Create a work order | ForestryStaff |
| GET | `/forestry/work-orders/{id}` | Fetch a work order | All roles |
| GET | `/forestry/work-orders` | List/filter work orders | All roles |
| POST | `/forestry/work-orders/{id}/start` | Start work (valid dig ticket + unexpired license) | Contractor |
| POST | `/forestry/work-orders/{id}/complete` | Complete work; cascade removal and permit close | Contractor |
| POST | `/forestry/work-orders/{id}/abort` | Abort a work order (no removal side effects) | ForestryStaff |
| POST | `/forestry/work-orders/{id}/dig-tickets` | Request an 811 locate ticket | Contractor |
| GET | `/forestry/work-orders/{id}/dig-tickets` | List dig tickets for a work order | All roles |
| GET | `/forestry/dig-tickets/{id}` | Fetch a dig ticket (lazily expires) | All roles |
| POST | `/forestry/dig-tickets/{id}/mark-valid` | Record 811 utility clearance | ForestryAdmin |
| POST | `/forestry/storm-events` | Declare a storm emergency over a zone | ForestryAdmin |
| GET | `/forestry/storm-events/{id}` | Fetch a storm event | All roles |
| GET | `/forestry/storm-events` | List/filter storm events | All roles |
| POST | `/forestry/storm-events/{id}/close` | Close an active storm event | ForestryAdmin |
| POST | `/forestry/_clock/set_current_utc` | Set the server's logical clock | ForestryAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_ZONE_NOT_FOUND` | 404 |
| `ERR_SPECIES_NOT_FOUND` | 404 |
| `ERR_TREE_NOT_FOUND` | 404 |
| `ERR_PERMIT_NOT_FOUND` | 404 |
| `ERR_INSPECTION_NOT_FOUND` | 404 |
| `ERR_CONTRACTOR_NOT_FOUND` | 404 |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 |
| `ERR_DIG_TICKET_NOT_FOUND` | 404 |
| `ERR_STORM_EVENT_NOT_FOUND` | 404 |
| `ERR_REPLACEMENT_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PERMIT_NOT_APPROVED` | 409 |
| `ERR_TREE_NOT_PROTECTED` | 422 |
| `ERR_INSPECTION_REQUIRED` | 422 |
| `ERR_PERMIT_NOT_ISSUED` | 409 |
| `ERR_EMERGENCY_NOT_DECLARED` | 422 |
| `ERR_DIG_TICKET_INVALID` | 409 |
| `ERR_DIG_WINDOW_INVALID` | 422 |
| `ERR_CONTRACTOR_DOUBLE_BOOKED` | 409 |
| `ERR_CONTRACTOR_LICENSE_EXPIRED` | 422 |
| `ERR_STORM_OVERLAP` | 409 |
| `ERR_FEE_AMOUNT_MISMATCH` | 422 |
| `ERR_FEE_UNPAID` | 402 |
