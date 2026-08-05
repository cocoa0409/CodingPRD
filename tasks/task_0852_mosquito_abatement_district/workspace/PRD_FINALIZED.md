# Mosquito Abatement District API — Product Requirements Document

## 1. Introduction

A mosquito abatement district is a public agency that carries a peculiar burden of proof: it may not spray a pesticide simply because residents are being bitten. Every application has to be justified against surveillance evidence — adult trap counts, larval dip surveys, degree-day accumulation, and arbovirus (West Nile virus) laboratory results — and every application has to respect the people and businesses that live downwind of it: beekeepers whose colonies collapse after an adulticide drift event, organic growers who lose certification, aquaculture ponds, and schoolyards. The district must also honor label re-entry intervals, keep a materially honest pesticide inventory, and answer the public's complaints inside a published service level. Today most districts stitch this together from spreadsheets, paper spray cards, and a separate complaint inbox, which means the audit trail linking a can of malathion to the trap count that justified it simply does not exist.

This document specifies the backend API for a district-wide vector control platform. The system models two coupled pipelines. The **evidence pipeline** flows from a trap collection logged in the field, through an arbovirus test pool in the laboratory, into a dated risk assessment that produces surveillance indices, and finally into a persisted **risk posture** on the service area itself. The **treatment pipeline** flows from a treatment plan justified by a confirmed assessment, through management approval (two distinct approvers when the modality is aerial), through protected-site notification, into committed and executed routes, and finally into a cost allocation. A third, public-facing pipeline handles complaints and reacts to posture escalation by raising service levels. The evidence pipeline gates the treatment pipeline; the treatment pipeline consumes a conserved pesticide ledger; and the complaint pipeline consumes the posture that the evidence pipeline produces.

Two design commitments run through every requirement below. First, **nothing is approximate**: indices, volumes, and money are computed by pinned arithmetic with pinned rounding points, because a regulator auditing a spray record will recompute the number by hand. Second, **nothing happens because time passed on a wall clock**: the server keeps a logical clock that test harnesses and operators drive explicitly, so that a re-entry interval or an acknowledgement window can be reproduced exactly.

---

## 2. Global Specifications & System-Wide Principles

### 2.1. District Personnel and Access Control

Every endpoint in this API — without exception, including the logical-clock endpoint and every read — requires authentication. A caller identifies itself with two headers on every request: `X-User-ID` and `X-User-Role`. If either header is absent, or is present but empty, or if `X-User-Role` does not spell one of the seven roles below exactly, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). No endpoint has an anonymous mode.

The seven roles are `DistrictAdmin`, `FieldTech`, `LabAnalyst`, `VectorEcologist`, `AbatementManager`, `SensitiveSiteOperator`, and `Resident`.

- A `DistrictAdmin` is the district's operations administrator. It maintains service areas, the protected-site and trap-site registries, pesticide stock, the applicator roster, and outbound spray notices, and it is the only role permitted to drive the logical clock.
- A `FieldTech` is a licensed field technician who runs traps, performs larval dips, logs weather, executes assigned treatment routes, and does the field work on complaints.
- A `LabAnalyst` is the arbovirus laboratory analyst who builds test pools from submitted collections and records West Nile virus results.
- A `VectorEcologist` authors risk assessments and drafts treatment plans, and — by deliberate design — can never approve one.
- An `AbatementManager` approves plans (never one it submitted itself), commits and settles routes, and manages the complaint queue.
- A `SensitiveSiteOperator` is the beekeeper or organic grower of record for a registered protected site, and acknowledges spray notices addressed to that site.
- A `Resident` is a member of the public filing mosquito complaints.

When the acting role is not among the roles listed for the endpoint in §4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403). The same code applies to a subtler case: several endpoints are shared by two roles because they drive a state machine whose individual actions have different actors. On any transition-driving endpoint, the acting role must be the role this document names as the actor of the specific requested action. An `AbatementManager` may not send the submit action on a plan, a `VectorEcologist` may not send the approve action, a `FieldTech` may not send the commit action, and only a `SensitiveSiteOperator` may send the acknowledge action on a notice — each such mismatch is `ERR_UNAUTHORIZED`, even though the role does appear in the endpoint's role list.

Two of the seven roles are **entity-backed**, meaning `X-User-ID` is not an arbitrary operator string but the identifier of a persisted record:

- When `X-User-Role` is `FieldTech`, `X-User-ID` is the `id` of the acting `Applicator`. Ownership checks on any resource that references an `Applicator` compare the resource's foreign-key field to `X-User-ID`: a trap collection's `recorded_by_applicator_id` when submitting it, a treatment route's `applicator_id` when executing it, and a service request's `assigned_applicator_id` when inspecting or resolving it. A mismatch is `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
- When `X-User-Role` is `SensitiveSiteOperator`, `X-User-ID` is the `id` of the acting `SensitiveSite`. Acknowledging a spray notice compares the notice's `sensitive_site_id` to `X-User-ID`, and a mismatch is likewise `ERR_NOT_RESOURCE_OWNER`.

The other five roles carry **opaque** identity. When `X-User-Role` is `DistrictAdmin`, `LabAnalyst`, `VectorEcologist`, `AbatementManager`, or `Resident`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — as `reported_by_user_id` on a filed complaint, as `submitted_by_user_id` on a plan, or as an entry in a plan's `approver_user_ids` list — but it never compares it to any entity's `id`. Because approval identity is opaque, the segregation-of-duties rules on plan approval are enforced purely by string comparison between `X-User-ID` values, yielding `ERR_SELF_APPROVAL` when an approver is also the submitter and `ERR_DUPLICATE_APPROVER` when the same identifier tries to approve twice.

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

Every list endpoint accepts two optional query parameters, `limit` and `offset`. When `limit` is omitted it defaults to 10; the smallest accepted value is 1 and the largest accepted value is 100. When `offset` is omitted it defaults to 0, and the smallest accepted value is 0. A `limit` below 1 or above 100, or a negative `offset`, is a request-shape failure and is rejected with `ERR_VALIDATION` (HTTP 422).

List results are ordered by `created_at` ascending. For the two entities that carry no `updated_at` — larval inspections and weather observations — this is still the ordering key, so the sequence in which rows were recorded is the sequence in which they are returned. The `meta` block of a list response carries `limit` and `offset` as they were applied, `total_count` as the number of rows matching the filters *before* the limit and offset were applied, and `has_more`, which is true when rows matching the filters remain beyond the current page.

Filters, where an endpoint declares them, are combined conjunctively with each other and with the path's implied scope; `total_count` always reflects the filtered set.

### 2.4. Resource Identity, Timestamps, and the Logical Clock

Every persisted resource carries a server-minted `id` that is a UUID string with no type prefix and no embedded semantics — clients must never parse it. Every resource also carries `created_at`, the instant the resource was persisted.

Most entities additionally carry `updated_at` and `version`. `updated_at` is refreshed on every mutation of the resource, and `version` is an integer that starts at 1 when the resource is created and increases by exactly 1 on each subsequent mutation. Two entities are deliberate exceptions because they are append-only evidence records and are never edited after the fact: a larval inspection and a weather observation carry only `id` and `created_at` — both `updated_at` and `version` are absent from their representations entirely.

All datetimes, on input and on output, are ISO 8601 UTC. Every server-rendered datetime field is rendered with **exactly three fractional-second digits** and a trailing `Z` — for example `2026-06-05T09:00:00.000Z`. This applies to `created_at` and `updated_at`, to every stamped instant (`sent_at`, `acknowledged_at`, `executed_at`, `confirmed_at`, `triaged_at`, `due_at`, `resolved_at`, `completed_at`, `result_recorded_at`, `last_positive_at`), and equally to client-supplied datetimes that the server stores and echoes back (`window_start`, `window_end`, `scheduled_start_at`). A client may submit either the plain `Z` form or the three-digit form; whichever it submits, the stored value is re-rendered in the three-digit form on the way out. Fields that are calendar dates rather than instants — `season_start_date`, `collection_date`, `inspection_date`, `obs_date`, `as_of_date`, `license_expires_on`, `registered_on` — are plain `YYYY-MM-DD` strings with no time component.

Every notion of "now" in this specification reads a **logical clock**, never the host's wall clock. At server startup the logical clock reads exactly `2026-05-01T00:00:00.000Z`, and it continues to read that value until it is explicitly moved; it must never silently fall back to real time. A `DistrictAdmin` moves it by supplying a `to_iso8601` instant to the clock-setting capability, which answers with the newly effective `current_utc`. Every instant the server stamps thereafter — including instants derived from the logical clock — is produced by the same three-digit renderer described above, so a stamped `executed_at` and a client-supplied `window_start` are formatted identically.

Whenever a rule speaks of an *N-day window ending on date D inclusive*, it means every calendar date from D minus (N − 1) days through D, comparing calendar dates in UTC. A 14-day window ending on 2026-06-14 therefore spans 2026-06-01 through 2026-06-14 and contains fourteen dates, not fifteen.

### 2.5. Path Resolution, Body References, and Nested Scope

Paths in this API are flat: each collection is a top-level segment, and nesting is at most one level deep, expressing a parent-child creation or listing relationship. Path identifiers are resolved **left to right**, and the first segment that fails to resolve determines the error. When a path names a service area that does not exist, the answer is `ERR_SERVICE_AREA_NOT_FOUND`; the analogous codes for the remaining path positions are `ERR_TRAP_SITE_NOT_FOUND`, `ERR_TRAP_COLLECTION_NOT_FOUND`, `ERR_LAB_POOL_NOT_FOUND`, `ERR_RISK_ASSESSMENT_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_APPLICATOR_NOT_FOUND`, `ERR_TREATMENT_PLAN_NOT_FOUND`, `ERR_TREATMENT_ROUTE_NOT_FOUND`, `ERR_NOTIFICATION_NOT_FOUND`, and `ERR_SERVICE_REQUEST_NOT_FOUND`. All ten are HTTP 404. A nested creation never accepts its parent identifier in the body: the child's parent foreign key is taken from the path.

Foreign keys that *do* travel in the body are resolved after every path identifier has resolved, and they are resolved in the order the endpoint's input list declares them — `service_area_id` first, then `trigger_assessment_id`, then `applicator_id`, then `pesticide_product_id`, then `sensitive_site_id`, then `assigned_applicator_id`. A body reference that does not resolve produces the 404 code for that reference's entity, so an unresolvable `sensitive_site_id` yields `ERR_SENSITIVE_SITE_NOT_FOUND` and an unresolvable `trigger_assessment_id` yields `ERR_RISK_ASSESSMENT_NOT_FOUND`.

Resolving successfully is not the same as belonging. Two cross-aggregate coherence checks reject references that resolve but point outside the aggregate the operation concerns, both with `ERR_AREA_MISMATCH` (HTTP 422): the triggering assessment named when a plan is drafted must belong to the same service area as the plan, and the protected site named when a spray notice is issued must belong to the plan's service area.

### 2.6. Numeric Precision, Decimals, and Money

All index, volume, and money arithmetic is exact decimal arithmetic — never binary floating point — and every rounding operation in this document rounds **half up** at the precision the rule declares.

- **Surveillance indices** (`abundance_index`, `larval_index`, `mir_provisional`, `mir_confirmed`, `vector_index_provisional`, `vector_index_confirmed`, `latest_confirmed_vector_index`) carry 2 decimal places. An empty input set yields exactly `0.00`, never null.
- **Degree days** (`degree_day` on an observation, `degree_days` on an assessment) carry 1 decimal place.
- **Pesticide volumes** (`label_rate_ml_per_acre`, `received_total_ml`, `on_hand_ml`, `committed_ml`, `applied_ml`, `estimated_volume_ml`, `actual_volume_ml`, `estimated_total_ml`) are millilitres with 2 decimal places.
- **Money** (`cost_cents_per_liter`, `material_cost_cents`, `labor_cost_cents`, `subtotal_cents`, `admin_fee_cents`, `total_cost_cents`) is always whole integer cents. No monetary field is ever fractional.
- **Distances** (`x_m`, `y_m`, `center_x_m`, `center_y_m`, `swath_radius_m`, `buffer_meters`, `buffer_meters_override`) are whole metres, while a computed separation distance is carried to 2 decimals before it is compared.

Where a total is assembled from parts, **the rounding point is pinned and it is never the end**. Two rules in particular are round-then-sum rather than sum-then-round: each day's degree-day contribution is rounded to 1 decimal before the days are added together, and each route's material cost is rounded to whole cents before the routes are added together. A plan's `estimated_total_ml` is likewise the sum of route volumes that were *already* rounded at commit time, not a fresh recomputation from acreage. Implementations that defer all rounding to the final step will produce different numbers and are wrong.

### 2.7. Version Guards on the Area Docket and the Pesticide Ledger

Two write operations are guarded by optimistic concurrency control, because both fold new information into a record whose prior contents the caller must have observed.

The first is opening a risk assessment against a service area. That request must carry `expected_service_area_version`, a non-optional field holding the `version` of the `ServiceArea` as the client last read it. If the value does not equal the area's current `version`, the request is rejected with `ERR_STALE_SERVICE_AREA_VERSION` (HTTP 412). The guard exists because a newly opened assessment supersedes the area's prior open assessment: a writer working from a stale view of the area would silently discard evidence that another writer had already folded into a newer assessment. A successful create increments the area's `version` by 1, so two consecutive creates from the same observed version cannot both succeed.

The second is posting a stock adjustment against a pesticide product. That request must carry `expected_product_version`, holding the `version` of the `PesticideProduct` as the client last read it; a mismatch with the product's current `version` is rejected with `ERR_STALE_PRODUCT_VERSION` (HTTP 412). Adjustments are additive against `received_total_ml` and `on_hand_ml`, so a writer working from a stale reading of the ledger would double-count a receipt or drive on-hand stock negative. A successful adjustment increments the product's `version` by 1.

No other endpoint accepts a version field. In particular, none of the transition-driving endpoints, and none of the creates other than the two named above, take an expected-version input — supplying one there has no meaning and no effect. Note that a product's `version` also advances as a side effect of route commitment, execution, voiding, and release, so a client that commits a route and then adjusts stock from its pre-commit reading of the product will be rejected by the product guard.

### 2.8. Surveillance Windows and the Evidence Horizon

Every surveillance index is computed over a **14-day window ending on the assessment's `as_of_date` inclusive**, and that same 14-day horizon governs the abundance, infection-rate, and larval components alike. Degree days are the exception: they accumulate over the closed interval from the area's `season_start_date` through `as_of_date`, so the weather component grows monotonically across a season while the other three components slide.

A second, independent 14-day horizon governs the positive-detection override on posture: a laboratory positive counts toward posture escalation for 14 days after the instant its result was recorded, measured against the logical clock rather than against any assessment date.

Evidence is also horizon-limited on the way in. A trap collection may only be submitted into the chain of custody within 7 days of the date it was collected, measured in calendar dates against the logical clock and inclusive at the boundary, so a collection exactly 7 days old still submits and one 8 days old does not.

### 2.9. The Pesticide Material Partition

Every pesticide product carries four volume fields that together form a conserved partition of the millilitres under district control:

> `on_hand_ml` plus `committed_ml` plus `applied_ml` always equals `received_total_ml`.

This identity holds exactly at 2 decimal places after every single mutation, and only five operations may move these fields. Committing a route moves its estimated volume out of `on_hand_ml` and into `committed_ml`. Executing a route moves the estimated volume out of `committed_ml`, adds the *actual* volume to `applied_ml`, and returns the difference between estimated and actual to `on_hand_ml` — a difference that is negative, and therefore a further withdrawal from on-hand stock, whenever the actual application exceeded the estimate. Voiding an executed or verified route removes the actual volume from `applied_ml` and returns it to `on_hand_ml`. Releasing a committed route removes the estimated volume from `committed_ml` and returns it to `on_hand_ml`. A stock adjustment adds its `delta_ml` to both `on_hand_ml` and `received_total_ml`, which is why a receipt or a write-off shifts the total without breaking the identity.

Because each movement is exactly compensating, commitment followed by release leaves all four fields exactly as they were, and execution followed by a void does the same. Every one of these five operations also advances the product's `version`.

### 2.10. The Complaint Case-Count Partition

Each service area maintains four integer counters over the complaints filed against it, and they too form a conserved partition:

> `request_open_count` plus `request_resolved_count` plus `request_closed_count` always equals `request_total_count`.

`request_total_count` counts every complaint ever filed for the area and never decreases. `request_open_count` counts complaints whose handling status is `RECEIVED`, `TRIAGED`, `ASSIGNED`, or `INSPECTED`. `request_resolved_count` counts those in `RESOLVED`, and `request_closed_count` counts those in `CLOSED`. Filing a complaint raises the total and the open count by one each. Resolving moves one case from open to resolved. Reopening moves it back from resolved to open, restoring all four counters exactly to their pre-resolution values. Closing from `RESOLVED` moves one from resolved to closed; closing directly from `RECEIVED` moves one from open to closed. Triage, assignment, and inspection move a complaint *within* the open bucket and therefore change none of the four counters.

### 2.11. Order of Validation

When a single request could fail several ways, the failure the caller sees is determined by a fixed precedence. Checks are evaluated in the following order, and the first failure short-circuits the request:

1. **Authentication** — both headers present, `X-User-Role` one of the seven declared roles, `X-User-ID` a non-empty string; otherwise `ERR_UNAUTHENTICATED`.
2. **Authorization** — the acting role is listed for the endpoint and, on a transition-driving endpoint, is the declared actor of the requested action; otherwise `ERR_UNAUTHORIZED`.
3. **Path existence** — every identifier in the path resolves, left to right, with the code matching the first unresolved segment.
4. **Body reference existence** — every foreign key in the body resolves, in the order the endpoint declares them.
5. **Ownership** — an entity-backed role acts only on resources it owns; otherwise `ERR_NOT_RESOURCE_OWNER`.
6. **Request shape** — required fields present, types correct, enum values inside their declared sets, numeric ranges honoured, and pagination inside its bounds; otherwise `ERR_VALIDATION`.
7. **Action validity** — on a transition-driving endpoint, the supplied `action` is one of that entity's declared actions; otherwise `ERR_INVALID_ACTION`.
8. **Optimistic concurrency** — `expected_service_area_version` or `expected_product_version` matches, where the endpoint requires one.
9. **Uniqueness** — no uniqueness constraint is violated; otherwise `ERR_DUPLICATE_RESOURCE` (HTTP 409).
10. **Transition existence** — the requested transition exists from the entity's current state, including terminal-state lockdown, under which no action whatsoever is accepted from a terminal state.
11. **Cross-entity state gates** — the related entities are in the states the transition requires.
12. **Segregation of duties** on plan approval.
13. **Applicator fitness** at route commitment.
14. **Referential coherence** — product method against plan modality, and cross-area references.
15. **Posture gate** on adulticide and aerial commitment.
16. **Protected-site clearance** on commitment.
17. **Re-entry interval** on commitment.
18. **Applicator occupancy** on commitment.
19. **Time windows** — collection age, schedule lead time, acknowledgement window, route window opening, plan start time, reopen window.
20. **Counting limits** — retest attempts, notification attempts, seasonal applications.
21. **Inventory sufficiency**, evaluated last of all.

Two consequences of this ordering deserve emphasis. Because ownership (step 5) precedes request shape (step 6), a `FieldTech` acting on someone else's route sees `ERR_NOT_RESOURCE_OWNER` rather than a complaint about a malformed body. And because inventory sufficiency is last (step 21), a commitment that is both short of stock and outside its applicator's licence category reports the licence problem, not the stock problem.

---

## 3. Business Logic & Workflows

### 3.1. Service Areas, the Protected-Site Registry, and Trap Sites

Everything in this system hangs off a **service area** — a named district zone that a `DistrictAdmin` registers before any surveillance can be recorded against it. Registration takes a human-readable `name` of 1 to 120 characters, a short zone `code` of 2 to 8 characters composed only of uppercase letters and digits, the `season_start_date` on which the abatement season begins (a calendar date that becomes the baseline for degree-day accumulation), and the resident `population` served, which must be zero or greater and is carried purely for reporting. Zone codes are unique across the whole district; a second area claiming a code already in use is rejected with `ERR_DUPLICATE_RESOURCE`.

A freshly registered area starts in a deliberately pessimistic-about-evidence, permissive-about-nothing state: `risk_posture` is `NORMAL`, `posture_source` is `NO_ASSESSMENT`, `latest_confirmed_vector_index` is `0.00`, `seasonal_application_count` is 0, all four of `request_total_count`, `request_open_count`, `request_resolved_count` and `request_closed_count` are 0, and `version` is 1. None of these are client-supplied; they are derived by the workflows described later in this section.

The **protected-site registry** records the neighbours the district must not poison. A `DistrictAdmin` registers a site inside an area, and the child's `service_area_id` is taken from the creation path rather than the body. Each entry declares a `site_type` — one of `APIARY`, `ORGANIC_FARM`, `AQUACULTURE`, or `SCHOOL` — together with the `operator_name` of record (1 to 120 characters), a `contact_email` that must contain an `@` character, and the district-grid coordinates of the site centre in metres as `x_m` (easting) and `y_m` (northing). The registry stamps `registered_on` with the logical clock's calendar date.

Each site type carries a default protection radius, and the district's negotiated practice is that bees and fish need the widest berth: an apiary and an aquaculture pond each default to 1600 metres, an organic farm to 800 metres, and a school to 400 metres. An operator who has negotiated something different is recorded with `buffer_meters_override`, an optional whole number of metres that must be zero or greater when supplied; omitting it, or supplying null, leaves the type default in force. Whichever applies, the effective radius is written to `buffer_meters` at registration — the override when one was supplied, otherwise the default for the declared `site_type` — and every later encroachment test reads `buffer_meters` and never re-derives it. The registry can be listed by any district role and, uniquely among area-scoped listings, by a `SensitiveSiteOperator` as well, optionally narrowed by `site_type`.

**Trap sites** are the fixed surveillance hardware of the area, also registered by a `DistrictAdmin` under the area path. A trap site carries the `site_code` stencilled on the trap (1 to 16 characters, unique among the trap sites of *its own* area, so two areas may reuse a code but one area may not), a `trap_type` of `CDC_LIGHT`, `GRAVID`, or `BG_SENTINEL`, the dominant `habitat` at the location — `URBAN`, `WETLAND`, `AGRICULTURAL`, or `STORMWATER` — and its own grid position as `x_m` and `y_m`. The boolean `is_active` marks whether the trap is in the current season's rotation and defaults to true when omitted; collections belonging to an inactive trap site are excluded from the abundance index entirely, which is how a decommissioned trap stops distorting the season's numbers without anyone deleting its history. Two laboratory-driven counters live on the trap site and start empty: `season_positive_count` is 0 and `last_positive_at` is null. The trap sites of an area can be listed, optionally filtered by `is_active`, and read individually.

### 3.2. Pesticide Stock and the Applicator Roster

Before a single route can be committed, the district must have product on the shelf and a licensed body to apply it. A `DistrictAdmin` adds a **pesticide product** with its trade `name` (1 to 120 characters), its `epa_reg_no` (1 to 32 characters, unique across the whole product catalogue), its `active_ingredient` — one of `BTI`, `METHOPRENE`, `PERMETHRIN`, `MALATHION`, or `NALED` — and the `application_method` the label permits, which is one of `LARVICIDE`, `ADULTICIDE`, or `AERIAL`. The label's `label_rate_ml_per_acre` must be strictly greater than zero and drives every volume computation. The label's `reentry_interval_hours` is a whole number of hours, zero or greater, and is the quarantine period after an application during which the same active ingredient may not be laid down again in the same area. The acquisition price is recorded as `cost_cents_per_liter`, a whole number of cents per litre that is zero or greater. The boolean `restricted_use` records whether the label is restricted-use and is carried for reporting only — it gates nothing. Finally, `received_total_ml` is the millilitre quantity taken into district stock, which must be strictly greater than zero and carries 2 decimals. On creation the ledger opens balanced: `on_hand_ml` equals `received_total_ml`, `committed_ml` is `0.00`, `applied_ml` is `0.00`, and `version` is 1. Duplicate EPA registration numbers are rejected with `ERR_DUPLICATE_RESOURCE`.

Stock moves for reasons other than spraying — a drum arrives, a container is found leaking and written off. A `DistrictAdmin` posts a **stock adjustment** carrying a signed `delta_ml`, a free-text `reason`, and `expected_product_version`. Both `on_hand_ml` and `received_total_ml` absorb the delta, which is exactly what keeps the four-field partition of §2.9 intact: shifting the total and the unreserved balance by the same amount leaves committed and applied stock untouched. An adjustment is refused with `ERR_INVENTORY_NEGATIVE` (HTTP 422) when it would drive `on_hand_ml` below `0.00`, and equally when it would bring `received_total_ml` to `0.00` or below — a district may write a product down but may never write it out of existence, since a zero-received product has no meaningful ledger. The version guard of §2.7 applies before the arithmetic: a stale `expected_product_version` is `ERR_STALE_PRODUCT_VERSION` and the adjustment does not happen. A successful adjustment bumps the product's `version` by 1, and the product's full four-field partition is readable at any time by any district role.

The **applicator roster** is where field identity comes from. A `DistrictAdmin` registers an applicator with `full_name` (1 to 120 characters), `license_no` (1 to 32 characters, unique across the roster), a `license_category`, and a `license_expires_on` calendar date. The returned `id` is the value a technician then presents as `X-User-ID` — the roster *is* the identity provider for the `FieldTech` role. A new applicator has `status` of `ACTIVE` and `assigned_route_count` of 0. A duplicate licence number is `ERR_DUPLICATE_RESOURCE`.

Licence category is a nested coverage hierarchy rather than a flat label. `LARVICIDE_ONLY` covers larvicide work alone. `ADULTICIDE` covers both larvicide and adulticide work. `AERIAL` covers all three modalities — larvicide, adulticide, and aerial. A licence therefore always covers everything below it and never anything above it, and the check performed at route commitment is whether the applicator's category covers the *product's* declared application method.

Duty status is administratively togglable: a `DistrictAdmin` may set an applicator's `status` to `ACTIVE` or `SUSPENDED`. Suspension is forward-looking only. A `SUSPENDED` applicator can no longer be committed to a new route nor assigned to a new complaint, but routes and assignments that already exist are left exactly as they are — the district does not retroactively unwind field work because a licence lapsed this morning. Attempting to assign a complaint to a suspended applicator is refused with `ERR_APPLICATOR_SUSPENDED` (HTTP 409), while attempting to commit a route to one is refused with `ERR_APPLICATOR_LICENSE_INVALID` (HTTP 422), since at commit time suspension is one of three ways an applicator can be unfit. The roster is readable per applicator, including duty status and current route load.

### 3.3. Adult Trap Surveillance and the Chain of Custody

Adult surveillance begins when a `FieldTech` empties a trap and logs a **trap collection** against the trap site. The technician supplies the `collection_date` the trap was emptied, the `trap_nights` this collection represents (at least 1, and the denominator of the abundance index), the `female_count` of female mosquitoes recovered (zero or greater, and the numerator), and the dominant `species` identified, which is one of `CULEX_PIPIENS`, `CULEX_TARSALIS`, `AEDES_AEGYPTI`, `AEDES_ALBOPICTUS`, or `OTHER`. The server takes `trap_site_id` from the path and writes `recorded_by_applicator_id` from the caller's `X-User-ID`, so authorship is never client-assertable. The new record opens with `status` of `LOGGED`, `pooled_mosquito_count` of 0, `positive_pool_count` of 0, and `wnv_detected` false. A trap site may hold at most one non-voided collection per calendar day: a second collection for the same trap site and the same `collection_date`, while an earlier one is still alive, is `ERR_DUPLICATE_RESOURCE`. Voiding the earlier one frees the slot.

A `LOGGED` collection is a private field note — it counts toward nothing. It enters the district's evidence base only when the logging technician submits it, advancing `LOGGED → SUBMITTED`. Submission is doubly restricted. Only the technician who logged it may submit it, so a caller whose `X-User-ID` differs from `recorded_by_applicator_id` is refused with `ERR_NOT_RESOURCE_OWNER` — a second technician cannot vouch for a colleague's trap. And the collection must still be fresh: the difference between the logical clock's calendar date and `collection_date` may be at most 7 days, inclusive at the boundary, so a collection exactly 7 days old still submits while one older than that is refused with `ERR_COLLECTION_WINDOW_EXPIRED` (HTTP 422). Once `SUBMITTED`, the collection is eligible both for the abundance index and for laboratory pooling. Submission also has a consequence one aggregate away: every risk assessment of the trap site's service area that is still `OPEN` is marked with `is_stale` true and `stale_reason` of `NEW_COLLECTION`, because the evidence base moved under an assessment that had already been computed.

Pooling drives the collection's status forward without any explicit request. The first pool created from a `SUBMITTED` collection advances it `SUBMITTED → POOLED` as a system transition, and adds that pool's `pool_size` to `pooled_mosquito_count`. Later pools created against an already-`POOLED` collection only add to `pooled_mosquito_count`; the status stays `POOLED`.

An `AbatementManager` may void a bad collection — a knocked-over trap, a mislabelled card. Voiding is available from `LOGGED`, where it succeeds unconditionally and simply excludes the collection from the abundance index permanently, and from `SUBMITTED`, where it succeeds only if no laboratory pool has ever been created from the collection; a `SUBMITTED` collection that already has at least one pool is refused with `ERR_COLLECTION_HAS_POOLS` (HTTP 409), because voiding it would orphan laboratory work. Both voids record the supplied `void_reason` and move the collection to `VOIDED`, which is terminal. Voiding from `SUBMITTED` carries the extra consequence that submission carried, in reverse: because the area's evidence base has again changed, every `OPEN` risk assessment of the area is marked `is_stale` true with `stale_reason` of `NEW_COLLECTION`. Voiding from `LOGGED` marks nothing stale, since a `LOGGED` collection was never in anyone's input set.

Collections are listable across the district with optional narrowing by `trap_site_id`, by `recorded_by_applicator_id`, and by `status`, and readable individually.

### 3.4. The Arbovirus Laboratory and the Positive-Detection Cascade

A `LabAnalyst` homogenises mosquitoes from a submitted collection into a **test pool**. Creating a pool takes the `pool_size` — the number of mosquitoes going into the tube, at least 1 and at most 50, since a pool larger than 50 mosquitoes cannot be reliably assayed — and an optional `assay`, which is `RT_PCR` or `VECTEST` and defaults to `RT_PCR`. The `trap_collection_id` comes from the path. A pool may only be built from a collection whose status is `SUBMITTED` or `POOLED`; a collection still `LOGGED`, or one that has been `VOIDED`, is refused with `ERR_COLLECTION_NOT_SUBMITTED` (HTTP 409). The new pool opens with `status` of `CREATED` and `retest_count` of 0.

Testing advances `CREATED → IN_TESTING` when the analyst starts the assay, and the same cross-entity gate applies here: the parent collection must still be `SUBMITTED` or `POOLED`, otherwise `ERR_COLLECTION_NOT_SUBMITTED`. Starting a first test leaves `retest_count` at whatever it was — this is the first test, not a retest.

From `IN_TESTING`, the analyst records a result, supplying `result` as `POSITIVE`, `NEGATIVE`, or `INVALID`. All three stamp `result_recorded_at` with the logical clock. A positive result may also carry an optional `ct_value`, the RT-PCR cycle threshold, which is stored for reporting and influences no calculation. A negative result moves the pool to `RESULT_NEGATIVE`, which is terminal, and marks every `OPEN` risk assessment of the area stale with `stale_reason` of `LAB_RESULT`. An inconclusive assay moves the pool to `INVALID`, leaves `retest_count` unchanged, likewise marks every `OPEN` assessment of the area stale with `LAB_RESULT`, and takes the pool out of *both* infection-rate variants until it is retested.

The `INVALID` state is the hinge of the laboratory's revision loop. An analyst may re-enter an invalid pool into testing, advancing `INVALID → IN_TESTING` and incrementing `retest_count` by 1 — the loop `INVALID → IN_TESTING → INVALID` may therefore run repeatedly. It is not unbounded: a pool may be retested only while `retest_count` is below 2, so the first and second retests are permitted and a third attempt, when `retest_count` has already reached 2, is refused with `ERR_RETEST_LIMIT_EXCEEDED` (HTTP 409). The alternative exit from `INVALID` is to discard the pool, advancing `INVALID → DISCARDED`, which is terminal. Discarding subtracts the pool's `pool_size` back out of the parent collection's `pooled_mosquito_count` and marks every `OPEN` assessment of the area stale with `LAB_RESULT`.

A **positive** result is the single most consequential event in the system, and it fans out through five hops that must all land before the request returns. The pool itself moves `IN_TESTING → RESULT_POSITIVE`, terminal, with `result_recorded_at` stamped and `ct_value` stored when supplied. Because that pool resulted positive, the parent collection's `positive_pool_count` increases by 1 and its `wnv_detected` becomes true — and `wnv_detected` is true precisely when `positive_pool_count` is 1 or more. Because that collection now shows a detection, the trap site's `season_positive_count` increases by 1 and its `last_positive_at` is stamped with the logical clock. Because that trap site has just recorded a fresh positive, every risk assessment of the site's service area whose status is `OPEN` gets `is_stale` true with `stale_reason` of `LAB_RESULT`. Because a laboratory positive now exists inside the area's 14-day escalation horizon, the area's `risk_posture` and `posture_source` are recomputed from scratch by the posture rule of §3.6. And finally, because the area's posture may have escalated, every complaint of that area whose handling status is `RECEIVED`, `TRIAGED`, `ASSIGNED`, or `INSPECTED` has its `priority` raised to the floor the new posture implies, and — for any such complaint whose `triaged_at` is not null — its `due_at` is recomputed from that unchanged `triaged_at` against the new priority. Complaints already `RESOLVED` or `CLOSED` are never touched.

Pools are listable across the district with optional narrowing by `trap_collection_id` and by `status`, and readable individually. A pool in `CREATED` or `DISCARDED` contributes to no infection-rate computation at all.

### 3.5. Larval Dips, Weather Records, and the Four Evidence Indices

Adult trapping is only one of four evidence streams. A `FieldTech` records a **larval inspection** — a dip survey — against an area, supplying the `inspection_date`, the number of standard dipper samples taken as `dips` (at least 1, and the denominator of the larval index), the total of larvae and pupae counted across all those dips as `larvae_count` (zero or greater, and the numerator), the `habitat` inspected, which is one of `CATCH_BASIN`, `DITCH`, `MARSH`, or `CONTAINER`, and the optional boolean `treated_on_site` recording whether the technician applied a spot larvicide during the visit. `treated_on_site` defaults to false and is reporting-only — an on-site spot treatment is deliberately *not* counted as a district application and does not touch `seasonal_application_count`. The area's `service_area_id` comes from the path. Larval inspections are append-only evidence: there is no status, no correction, and no void, and they carry neither `updated_at` nor `version`. Each inspection immediately enters the larval-index input set for every window that contains its `inspection_date`. Inspections of an area are listable, optionally narrowed by `habitat`.

**Weather observations** are the fourth stream and may be recorded by either a `DistrictAdmin` or a `FieldTech`. An observation carries the `obs_date` it describes, the day's maximum air temperature `tmax_c` and minimum air temperature `tmin_c` in degrees Celsius — each between −50.0 and 60.0 with at most one decimal place, and `tmin_c` must not exceed `tmax_c` — and an optional `rainfall_mm` in millimetres, zero or greater, defaulting to `0.0` and carried for reporting only. An area may hold at most one observation per calendar day; a second observation for the same area and the same `obs_date` is `ERR_DUPLICATE_RESOURCE`. Like larval inspections, weather observations are append-only and carry neither `updated_at` nor `version`, and they are listable per area.

Each observation's contribution to seasonal warmth is computed and stored at the moment it is recorded, as `degree_day`. Take the day's mean temperature — the sum of `tmax_c` and `tmin_c` divided by two — and subtract the development base temperature of 10.0 degrees Celsius. Round that difference half up to one decimal place. If the rounded result is negative, `degree_day` is `0.0`; otherwise `degree_day` is the rounded result. A cold day contributes nothing, never a debt against warm days.

**Degree-day accumulation** for an assessment then sums those already-rounded daily values over the observations of the area whose `obs_date` falls in the closed interval from the area's `season_start_date` through the assessment's `as_of_date`, processing them in ascending `obs_date` order, and rounds the sum half up to one decimal place. The rounding point here is pinned and must not be moved: each day is rounded to one decimal *before* summing. Two days whose raw values are 12.55 and 11.55 accumulate as 12.6 plus 11.6, giving 24.2 — not the 24.1 that summing raw values and rounding once at the end would produce. Observations dated before the season start are excluded outright, no matter how warm they were.

The **trap abundance index** measures adult density over the 14-day window ending on `as_of_date` inclusive. It considers trap collections whose trap site belongs to the area, whose trap site has `is_active` true, whose `status` is either `SUBMITTED` or `POOLED`, and whose `collection_date` falls inside the window. Sum `female_count` across those collections to get the numerator, sum `trap_nights` across the same collections to get the denominator, and divide, rounding half up to two decimal places. When the summed trap-nights are zero — because nothing qualified — the index is exactly `0.00`. Collections still `LOGGED`, collections `VOIDED`, and collections belonging to an inactive trap site never enter the numerator or the denominator.

The **larval index** measures immature density over the same 14-day window. Sum `larvae_count` across the area's inspections whose `inspection_date` falls in the window to get the numerator, sum `dips` across the same inspections to get the denominator, and divide, rounding half up to two decimal places. Zero total dips yields exactly `0.00`. There is no status filter, because larval inspections have no status.

The **minimum infection rate** measures how much West Nile virus the laboratory is finding, expressed per thousand mosquitoes tested. Start from the candidate pools: every test pool whose parent collection belongs to a trap site of this area, whose parent collection's `collection_date` falls inside the same 14-day window, and whose parent collection's `status` is `SUBMITTED` or `POOLED`. Then filter those candidates by pool status, and here the specification forks into **two variants that differ in exactly one respect** — the treatment of pools still in testing. Both variants exclude pools in `CREATED`, pools in `DISCARDED`, and pools in `INVALID`.

- The **provisional** variant includes pools in `IN_TESTING`, `RESULT_POSITIVE`, and `RESULT_NEGATIVE`. A pool still on the bench is treated as presumed negative: its `pool_size` enters the denominator while it contributes nothing to the numerator, which dilutes the rate downward.
- The **confirmed** variant includes only pools in `RESULT_POSITIVE` and `RESULT_NEGATIVE`. Pools still on the bench are dropped from the numerator *and* the denominator, which raises the rate relative to the provisional variant for exactly the same untouched data.

In either variant, sum `pool_size` across the included pools to get the total mosquitoes tested, count the included pools whose status is `RESULT_POSITIVE`, divide that count by the total mosquitoes tested, multiply by 1000, and round half up to two decimal places. When the total mosquitoes tested is zero, the rate is exactly `0.00`.

The **vector index** is the district's single composite risk number, on a 0-to-100 scale, and it is a weighted score over four normalised components. Each component takes its raw index, divides by that component's reference level, multiplies by 100, rounds half up to two decimal places, and is then capped at `100.00`:

- The abundance component normalises the abundance index against a reference of 50.0 females per trap-night.
- The infection component normalises the minimum infection rate against a reference of 10.0 per thousand.
- The larval component normalises the larval index against a reference of 4.0 larvae per dip.
- The weather component normalises accumulated degree days against a reference of 400.0.

The four capped components are then weighted and added: the abundance component at 0.40, the infection component at 0.35, the larval component at 0.15, and the weather component at 0.10. Onto that weighted sum sits a **non-linear outbreak amplification**. When the infection component is strictly greater than `0.00` *and* the abundance component is at or above 50.0, the weighted sum is multiplied by 1.25 — the epidemiological judgement being that virus circulating amid a dense adult population is disproportionately dangerous. The abundance trigger is inclusive: a component of exactly `50.00` does fire the amplification. Finally the result — amplified or not — is rounded half up to two decimal places and capped at `100.00`. The order is pinned: components are each rounded before weighting, the multiplication happens on the unrounded weighted sum, and only then is the final value rounded.

The vector index inherits the infection-rate fork. Its abundance, larval, and weather components are identical in both variants because they read the assessment's own stored `abundance_index`, `larval_index`, and `degree_days`. Only the infection component differs: the provisional variant consumes `mir_provisional`, the confirmed variant consumes `mir_confirmed`. Whenever at least one pool is still in testing and at least one pool is positive, the confirmed variant therefore yields a strictly higher index than the provisional one for the same untouched surveillance data.

A `VectorEcologist` opens a **risk assessment** against an area by supplying the `as_of_date` on which the surveillance windows close, together with `expected_service_area_version`. The new record is stamped `status` of `OPEN` with `is_stale` false and `stale_reason` null, and all five provisional numbers are computed and frozen onto it at that instant: `abundance_index`, `larval_index`, `degree_days`, `mir_provisional`, and `vector_index_provisional`. The two confirmed-variant fields, `mir_confirmed` and `vector_index_confirmed`, remain null, as do `posture_at_confirm` and `confirmed_at`. Any *other* assessment of the same area that was still `OPEN` is moved to `SUPERSEDED` as a system transition, keeping its own provisional numbers untouched as a historical record with no recomputation. The area's `version` increases by 1. Assessments of an area are listable, optionally narrowed by `status`, and each is readable individually with both index variants exposed.

### 3.6. Staleness, Confirmation, and How Posture Is Derived

An open assessment is a snapshot, and snapshots rot. Whenever the evidence underneath an area moves while an assessment of that area is still `OPEN`, the assessment is flagged: `is_stale` becomes true and `stale_reason` records which kind of evidence moved. Submitting a new collection into the chain of custody, or voiding a collection that had already been submitted, sets `stale_reason` to `NEW_COLLECTION`. Any laboratory outcome — a positive, a negative, an inconclusive result, or a discard — sets `stale_reason` to `LAB_RESULT`. The flag is advisory rather than blocking: a stale assessment may still be confirmed, and the district accepts that because the confirmed variant is recomputed at confirmation time anyway, against the pool set as it stands *then*. What the flag tells an ecologist is that the provisional numbers on the record no longer describe the world.

Confirmation is the act that gives an assessment legal force, and only a `VectorEcologist` performs it. The assessment must be `OPEN`; confirming one that is already `CONFIRMED` or `SUPERSEDED` is refused with `ERR_ASSESSMENT_NOT_OPEN` (HTTP 409). Confirmation advances `OPEN → CONFIRMED` and does five things. It computes and writes `mir_confirmed` and `vector_index_confirmed` from the confirmed variants described above, evaluated against the pool set as it stands at confirmation time rather than as it stood at creation time. It stamps `confirmed_at` with the logical clock. It moves any *other* assessment of the same area whose status was `CONFIRMED` to `SUPERSEDED`, so an area has at most one live confirmed assessment. It copies this assessment's `vector_index_confirmed` into the area's `latest_confirmed_vector_index` and re-derives the area's `risk_posture` and `posture_source`. And it records the resulting posture onto the assessment as `posture_at_confirm`, freezing what the confirmation actually decided.

**Posture derivation** combines an index reading with a positive-detection override, and takes whichever is more alarming. Begin with the area's `latest_confirmed_vector_index`, which is `0.00` when no assessment of the area has ever been confirmed. If that value is at or above 70.0 the index reading is `EMERGENCY`; otherwise, if it is at or above 40.0 the index reading is `ELEVATED`; otherwise it is `NORMAL`. Both thresholds are inclusive on the low side, so exactly `40.00` is `ELEVATED` and exactly `70.00` is `EMERGENCY`. Separately, ask whether a positive detection is recent: does there exist any test pool in `RESULT_POSITIVE` whose parent collection belongs to a trap site of this area and whose `result_recorded_at` is at or after the logical clock minus 14 days? If such a pool exists, the override reading is `ELEVATED`; if not, it is `NORMAL`. Rank the three postures with `NORMAL` lowest, `ELEVATED` above it, and `EMERGENCY` highest, and set `risk_posture` to the higher-ranked of the index reading and the override reading.

`posture_source` explains which branch won. It is `POSITIVE_OVERRIDE` when the override reading outranks the index reading. It is `NO_ASSESSMENT` when no assessment of the area has ever been confirmed and the override did not outrank the index reading. Otherwise it is `INDEX`. Note the consequence: an area with no confirmed assessment but a fresh laboratory positive lands on `ELEVATED` with `posture_source` of `POSITIVE_OVERRIDE`, and an area with a confirmed index of exactly `40.00` and no recent positive lands on `ELEVATED` with `posture_source` of `INDEX`. Posture is recomputed at exactly two moments — when an assessment is confirmed, and when a laboratory pool resulted positive — and never on a timer, so an override that ages past 14 days does not lapse by itself; it lapses the next time the posture is recomputed.

When a recomputation leaves the area's posture at a strictly higher rank than it had before, the escalation **fans out into the complaint queue**. Each posture implies a priority floor: `NORMAL` implies `ROUTINE`, `ELEVATED` implies `PRIORITY`, and `EMERGENCY` implies `URGENT`, with those three priorities ranked `ROUTINE` lowest, then `PRIORITY`, then `URGENT`. Every complaint of the area whose handling status is `RECEIVED`, `TRIAGED`, `ASSIGNED`, or `INSPECTED` — processed in ascending `created_at` order, though the order has no observable effect because the rows are independent — has its `priority` set to the higher-ranked of its current priority and the new floor. Where that comparison actually changed a complaint's priority and the complaint has a non-null `triaged_at`, its `due_at` is recomputed against the new priority. Priority is strictly monotone: escalation never lowers a priority, and a *later* posture drop never lowers one either — nothing in this system reduces a complaint's `priority` once it has been raised, not even reopening it. Complaints in `RESOLVED` or `CLOSED` are outside the escalation set entirely.

### 3.7. Drafting, Approving, and Revising a Treatment Plan

A **treatment plan** is the district's authorisation document, and a `VectorEcologist` drafts it. The draft names the `service_area_id` to be treated, the `trigger_assessment_id` of the risk assessment that constitutes the surveillance justification, and the `treatment_type`, which is one of `LARVICIDE`, `ADULTICIDE`, or `AERIAL`. The named assessment must belong to the same area as the plan; an assessment that resolves but points at a different area is refused with `ERR_AREA_MISMATCH`. Note that at draft time the assessment need not yet be confirmed — an ecologist may prepare a plan against an open assessment and confirm it later.

Drafting fixes two derived properties that shape the whole downstream workflow. `required_approvals` is 2 when `treatment_type` is `AERIAL` and 1 otherwise, because putting product into the air over a district demands two independent managers. `notification_required` is true when `treatment_type` is `ADULTICIDE` or `AERIAL`, and false for `LARVICIDE`, since larvicide goes into standing water rather than into the air column. The rest of the record opens empty: `status` is `DRAFT`, `submitted_by_user_id` is null, `approver_user_ids` is an empty list, `revision_count` is 0, `scheduled_start_at` is null, `completed_at` is null, `cancel_reason` and `return_reason` are null, `estimated_total_ml` is `0.00`, `admin_fee_rate` is `0.0`, and `material_cost_cents`, `labor_cost_cents`, `subtotal_cents`, `admin_fee_cents`, and `total_cost_cents` are all 0.

Routes are attached to the plan while it is still editable, and only by the drafting role. A `VectorEcologist` adds a route to a plan whose `status` is `DRAFT` or `RETURNED`; attaching a route to a plan in any other state — already submitted, already approved, cancelled — is refused with `ERR_INVALID_TRANSITION`. A route declares the `applicator_id` who will run it and the `pesticide_product_id` to be applied (both body references, resolved in that order), a `route_code` of 1 to 16 characters that must be unique among the routes of *its own* plan (a collision is `ERR_DUPLICATE_RESOURCE`), the planned occupancy interval as `window_start` and `window_end` where `window_end` must fall strictly after `window_start`, the `planned_acres` to be treated as a value strictly greater than zero with 2 decimals, and the route's geometry as the district-grid centre `center_x_m` and `center_y_m` plus an optional `swath_radius_m`, the half-width of the treated swath in metres, which defaults to 0 and must be zero or greater. The server derives `duration_minutes` as the whole number of minutes between `window_start` and `window_end`, which is therefore always at least 1, opens the route with `status` of `PLANNED`, and leaves `estimated_volume_ml` at `0.00` until commitment. The `treatment_plan_id` is taken from the path.

Submission moves the plan `DRAFT → SUBMITTED` and is performed by a `VectorEcologist`. Two preconditions guard it. The plan must have at least one route in `PLANNED` — an empty authorisation is refused with `ERR_INVALID_TRANSITION`. And the triggering assessment must by now have reached `CONFIRMED`; a plan whose justification is still `OPEN`, or has been `SUPERSEDED`, is refused with `ERR_TRIGGER_ASSESSMENT_NOT_CONFIRMED` (HTTP 409). This is the seam where the evidence pipeline gates the treatment pipeline. On success the submitter's `X-User-ID` is recorded as `submitted_by_user_id`.

Approval belongs exclusively to `AbatementManager`, and the district's segregation-of-duties rule is absolute: **the approver's `X-User-ID` must differ from `submitted_by_user_id`**, and a manager who tries to approve or return a plan they themselves submitted is refused with `ERR_SELF_APPROVAL` (HTTP 403). A manager whose `X-User-ID` already appears in `approver_user_ids` is refused with `ERR_DUPLICATE_APPROVER` (HTTP 409) — one body, one signature. Where a valid approval lands depends on the quorum. When the number of approvers already recorded plus this one is still fewer than `required_approvals`, the manager's `X-User-ID` is appended to `approver_user_ids` and the plan **stays in** `SUBMITTED`: this is the aerial case after a single approval, and the response reports a plan still awaiting its second signature. When the number of approvers already recorded plus this one equals `required_approvals`, the identifier is appended and the plan advances `SUBMITTED → APPROVED`. A larvicide or adulticide plan therefore joins after one approval and an aerial plan only after two distinct approvers, and reaching `APPROVED` is what unlocks both route commitment and the issuing of spray notices.

A manager who is unconvinced returns the plan instead, advancing `SUBMITTED → RETURNED` with the supplied `return_reason` stored and `revision_count` increased by 1. Returning is bound by the same segregation-of-duties rule as approving, so a manager may not return a plan they submitted. From `RETURNED` the drafting ecologist revises, advancing `RETURNED → DRAFT`, which resets `approver_user_ids` to an empty list and `submitted_by_user_id` back to null — every signature collected on the previous revision is discarded, so a re-submitted aerial plan must again gather two approvals. The cycle `DRAFT → SUBMITTED → RETURNED → DRAFT` may run any number of times, and `revision_count` records how many times the plan has been sent back.

Cancellation is available to an `AbatementManager` from `DRAFT`, `SUBMITTED`, `RETURNED`, `APPROVED`, `SCHEDULED`, and `SUSPENDED`, in every case with identical effects, and is **not** available once the plan is `IN_PROGRESS` — a crew in the field is stopped by suspending the plan, not by cancelling it — nor from the two terminal states `COMPLETED` and `CANCELLED`. Cancellation stores the supplied `cancel_reason`, moves the plan to `CANCELLED`, and unwinds everything the plan was holding. Every route of the plan still in `PLANNED` becomes `RELEASED` with no inventory movement, since nothing had been reserved. Every route in `COMMITTED` becomes `RELEASED` and gives back its reservation exactly as an explicit release would: the route's `estimated_volume_ml` leaves `committed_ml` and returns to `on_hand_ml`, the product's `version` advances, and the applicator's `assigned_route_count` decreases by 1. Every notice of the plan in `QUEUED` or `SENT` becomes `EXPIRED`, so no further delivery attempt is possible.

Plans are listable with optional narrowing by `service_area_id`, by `trigger_assessment_id`, and by `status`, and each plan is individually readable with its approvals and cost allocation exposed.

### 3.8. Spray Notices, Protected-Site Clearance, and Scheduling the Operation

Before product goes into the air near a registered apiary or organic farm, the operator must have been told. A `DistrictAdmin` issues a **spray notice** against a plan, naming the `sensitive_site_id` being notified and optionally the `channel` of record — `EMAIL`, `SMS`, or `PHONE`, defaulting to `EMAIL`. A notice may only be issued while the plan is `APPROVED` or `SCHEDULED`; issuing one against a plan in any other state is refused with `ERR_INVALID_TRANSITION`. The site must belong to the plan's service area, or the request is refused with `ERR_AREA_MISMATCH`. At most one *live* notice may exist per plan-and-site pairing: while a notice for that pairing is in `QUEUED`, `SENT`, or `ACKNOWLEDGED`, a second one is refused with `ERR_DUPLICATE_RESOURCE`. Once the first notice has landed in `FAILED`, `EXPIRED`, or `UNDELIVERABLE`, the pairing is free again and a replacement may be issued. A new notice opens with `status` of `QUEUED` and `attempt_count` of 0, with `sent_at`, `acknowledged_at`, and `failure_reason` all null, and `treatment_plan_id` taken from the path.

Delivery is a retry cycle driven by a `DistrictAdmin`. Sending advances `QUEUED → SENT`, requires the parent plan to be `APPROVED` or `SCHEDULED`, increases `attempt_count` by 1, and stamps `sent_at` with the logical clock. A failed delivery — a bounced address, an unanswered phone — advances `SENT → FAILED` with the supplied `failure_reason` stored. From `FAILED` the admin either requeues, advancing `FAILED → QUEUED` so a further send may be attempted, or gives up, advancing `FAILED → UNDELIVERABLE`, which is terminal. Requeueing deliberately does *not* clear `sent_at`: the previous attempt's instant is retained until the next send overwrites it. The district allows at most 3 delivery attempts in total: sending or requeueing while `attempt_count` has already reached 3 is refused with `ERR_NOTIFICATION_ATTEMPTS_EXHAUSTED` (HTTP 409). An `UNDELIVERABLE` notice can never satisfy the scheduling precondition below, so the plan cannot proceed until a *replacement* notice for the same site reaches `ACKNOWLEDGED` or `EXPIRED`.

A sent notice has a 24-hour acknowledgement window. The owning `SensitiveSiteOperator` — and only that operator, matched by comparing `X-User-ID` to the notice's `sensitive_site_id`, with `ERR_NOT_RESOURCE_OWNER` otherwise — acknowledges it, advancing `SENT → ACKNOWLEDGED` and stamping `acknowledged_at`. Acknowledgement is permitted while the logical clock is at or before `sent_at` plus 24 hours, inclusive at the boundary, so an acknowledgement landing at exactly 24 hours still succeeds; later than that it is refused with `ERR_ACK_WINDOW_EXPIRED` (HTTP 422). The mirror-image action belongs to the `DistrictAdmin`: expiring an unacknowledged notice advances `SENT → EXPIRED` and is permitted only **strictly after** `sent_at` plus 24 hours. At exactly 24 hours the operator may still acknowledge, so expiring at that instant is refused with `ERR_ACK_WINDOW_OPEN` (HTTP 409). The two windows are complementary and share a single boundary instant, which belongs to the operator. An `EXPIRED` notice counts as *served* for scheduling purposes — the district discharged its duty to inform even though nobody replied. Notices are listable with optional narrowing by `treatment_plan_id`, by `sensitive_site_id`, and by `status`, and are readable individually; both listings and reads are additionally available to `SensitiveSiteOperator`.

**Encroachment** is the geometric test that decides which protected sites a route actually threatens. For a route and a protected site of the route's plan's area, take the district-grid separation between the route centre and the site centre — the square root of the sum of the squared difference between `center_x_m` and `x_m` and the squared difference between `center_y_m` and `y_m` — and round that distance half up to two decimal places. The route encroaches on the site when that rounded distance is less than or equal to the site's `buffer_meters` plus the route's `swath_radius_m`. The comparison is inclusive: a separation exactly equal to the combined radius counts as encroachment. A wide swath therefore reaches further than its centre suggests, and a negotiated `buffer_meters_override` moves the boundary for that site alone.

Scheduling is where the notice discipline is enforced, and it is performed by an `AbatementManager` supplying `scheduled_start_at`. The plan advances `APPROVED → SCHEDULED` only when four conditions hold. First, the plan must have at least one route in `COMMITTED` and no route still in `PLANNED`; otherwise the request is refused with `ERR_NO_COMMITTED_ROUTE` (HTTP 409) — every route must have been either committed, released, or voided before an operational date is fixed. Second, every notice of the plan must be in `ACKNOWLEDGED` or `EXPIRED`; a notice still `QUEUED`, still `SENT`, sitting in `FAILED`, or written off as `UNDELIVERABLE` is refused with `ERR_NOTIFICATION_INCOMPLETE` (HTTP 409). Third, for every protected site of the plan's area of type `APIARY` or `ORGANIC_FARM` that is encroached upon by a `COMMITTED` route of this plan, a notice of this plan addressed to that site must exist in `ACKNOWLEDGED` or `EXPIRED` — a plan cannot be scheduled merely because it issued no notices, and the absent notice is likewise `ERR_NOTIFICATION_INCOMPLETE`. Fourth, the lead time must be sufficient: the interval from the logical clock to `scheduled_start_at` must be at least 48 hours for an `AERIAL` plan and at least 24 hours for a `LARVICIDE` or `ADULTICIDE` plan, inclusive at the boundary so exactly the required lead passes; a shorter lead is refused with `ERR_NOTIFICATION_LEAD_TIME` (HTTP 422). On success `scheduled_start_at` is stored.

Starting the operation advances `SCHEDULED → IN_PROGRESS` and is permitted only when the logical clock has reached `scheduled_start_at`, inclusive; starting earlier is refused with `ERR_PLAN_START_TOO_EARLY` (HTTP 409). Only from `IN_PROGRESS` may routes be executed. Weather intervenes often enough that the district needs a hold: an `AbatementManager` suspends the plan, advancing `IN_PROGRESS → SUSPENDED`, which blocks route execution, and resumes it, advancing `SUSPENDED → IN_PROGRESS`, which unblocks it. The cycle `IN_PROGRESS → SUSPENDED → IN_PROGRESS` may repeat as often as the wind demands.

### 3.9. Committing, Executing, and Settling Routes — and What a Treatment Costs

**Commitment** is the district's compliance checkpoint, and it is where nine separate conditions converge on a single `AbatementManager` action. A route advances `PLANNED → COMMITTED` only when every one of them holds, and they are evaluated in the fixed order below so that the caller always learns about the most fundamental problem first:

1. The parent plan must be `APPROVED`. A plan still in draft, still gathering signatures, returned, already scheduled, or already running cannot take new commitments — `ERR_PLAN_NOT_APPROVED` (HTTP 409).
2. The applicator must be fit, which means three things at once: `status` is `ACTIVE`, `license_expires_on` falls on or after the calendar date of `window_start` (a licence expiring on the day of the work is still valid), and `license_category` covers the product's `application_method` under the coverage hierarchy of §3.2. Any of the three failing yields `ERR_APPLICATOR_LICENSE_INVALID` (HTTP 422).
3. The product's `application_method` must equal the plan's `treatment_type`; loading an adulticide onto a larvicide plan is `ERR_PRODUCT_METHOD_MISMATCH` (HTTP 422).
4. The **posture gate**: when the plan's `treatment_type` is `ADULTICIDE` or `AERIAL`, the area's `risk_posture` must be `ELEVATED` or `EMERGENCY` at commit time. Adult spraying against a `NORMAL` posture is exactly the unjustified application this system exists to prevent, and it is refused with `ERR_POSTURE_TOO_LOW` (HTTP 409). Larvicide commitment is not posture-gated at all.
5. **Protected-site clearance**: again only when `treatment_type` is `ADULTICIDE` or `AERIAL`, for every protected site of type `APIARY` or `ORGANIC_FARM` that this route encroaches upon by the geometric test of §3.8, a notice of this plan addressed to that site must already exist in `SENT` or `ACKNOWLEDGED`. Note the deliberate asymmetry with scheduling: clearance at commit time accepts a merely `SENT` notice, because the operator has been told and the work has not yet been dated, whereas scheduling demands `ACKNOWLEDGED` or `EXPIRED`. Missing clearance is `ERR_SENSITIVE_SITE_NOT_CLEARED` (HTTP 409). Sites of type `AQUACULTURE` and `SCHOOL` are recorded and reported but do not gate commitment.
6. The **re-entry interval**, evaluated per active ingredient across the whole service area rather than per route or per plan. Take the re-entry interval declared on the product this route will apply, and consider every *other* route in the same service area whose status is `EXECUTED` or `VERIFIED` and whose product shares this route's `active_ingredient`. The commitment is refused when this route's `window_start` falls at or before that earlier route's `window_end` plus that re-entry interval. The boundary is a violation: a start exactly at the end-of-quarantine instant is rejected, and only a start strictly after it is allowed. Routes still `PLANNED`, `COMMITTED`, `VOIDED`, or `RELEASED` never create a quarantine, because nothing was actually laid down. The rejection is `ERR_REENTRY_INTERVAL_VIOLATION` (HTTP 409).
7. **Applicator occupancy**, evaluated with a trailing turnaround buffer of 45 minutes for equipment cleanout and travel. A route's effective occupancy runs from its `window_start` up to but not including its `window_end` plus 45 minutes. Consider every other route with the same `applicator_id` whose status is `COMMITTED`, `EXECUTED`, or `VERIFIED`; the commitment is refused when this route's `window_start` falls strictly before that route's `window_end` plus 45 minutes **and** that route's `window_start` falls strictly before this route's `window_end` plus 45 minutes. Because both comparisons are strict, occupancies that merely touch at the buffer boundary do not conflict — a route starting exactly 45 minutes after another ends is accepted. A genuine overlap is `ERR_APPLICATOR_ROUTE_CONFLICT` (HTTP 409).
8. The **seasonal cap**: an area may absorb at most 2 applications in a season, so commitment requires the area's `seasonal_application_count` to be below 2 and is otherwise refused with `ERR_SEASONAL_LIMIT_EXCEEDED` (HTTP 409).
9. **Inventory sufficiency**, evaluated last: the product's `on_hand_ml` must be at least the route's estimated volume, or the commitment is refused with `ERR_INSUFFICIENT_INVENTORY` (HTTP 409).

The **estimated volume** that condition 9 tests is computed from the plan on paper: multiply the route's `planned_acres` by the product's `label_rate_ml_per_acre` and round half up to two decimal places. On success it is written to the route's `estimated_volume_ml`, and the reservation moves through the ledger: `on_hand_ml` decreases by that amount, `committed_ml` increases by the same amount, and the product's `version` advances by 1. The applicator's `assigned_route_count` increases by 1. The plan's `estimated_total_ml` is then recomputed as the sum of `estimated_volume_ml` across the routes of that plan whose status is `COMMITTED`, `EXECUTED`, or `VERIFIED` — a sum of values that were each already rounded at their own commit time, never a fresh recomputation from acreage. Routes in `PLANNED`, `RELEASED`, or `VOIDED` contribute nothing to that total.

**Execution** is the one route action that belongs to the field rather than to the office. The assigned `FieldTech` — and only that technician, matched by comparing `X-User-ID` to the route's `applicator_id`, with `ERR_NOT_RESOURCE_OWNER` otherwise — advances the route `COMMITTED → EXECUTED`, supplying the `actual_acres` actually treated (strictly greater than zero) and the `wind_speed_mph` measured at application (zero or greater). The parent plan must be `IN_PROGRESS`; a plan that is merely `SCHEDULED`, or one currently `SUSPENDED` for weather, is refused with `ERR_PLAN_NOT_IN_PROGRESS` (HTTP 409). The logical clock must also have reached the route's `window_start`, inclusive; executing early is refused with `ERR_ROUTE_WINDOW_NOT_OPEN` (HTTP 409).

The **actual volume** differs from the estimate in two ways: it uses the acreage actually covered, and it carries a wind drift adjustment. When the reported `wind_speed_mph` is at or above 8.0 miles per hour, the drift factor is 1.10 — a breezy application loses ten percent of its product to drift and therefore consumes ten percent more to cover the same ground. Below 8.0 miles per hour the factor is 1.00. The trigger is inclusive, so exactly 8.0 miles per hour already incurs the surcharge. Multiply `actual_acres` by the product's `label_rate_ml_per_acre` and by the drift factor, round half up to two decimal places, and write the result to `actual_volume_ml`. Before that write is accepted, the ledger is checked one last time: the product's `on_hand_ml` plus the route's `estimated_volume_ml` minus the actual volume must be zero or greater, and a shortfall is `ERR_INSUFFICIENT_INVENTORY`. On success `executed_at` is stamped from the logical clock, `committed_ml` decreases by the estimated volume, `applied_ml` increases by the actual volume, `on_hand_ml` absorbs the estimated volume minus the actual volume — a *withdrawal* whenever the crew overshot its estimate — the product's `version` advances, and the area's `seasonal_application_count` increases by 1.

An `AbatementManager` closes out the paperwork by verifying the route, advancing `EXECUTED → VERIFIED`, which moves no material and exists solely to make the route eligible for the cost allocation. The compensating action is the void, available from both `EXECUTED` and `VERIFIED` with identical effects, storing the supplied `void_reason` and moving the route to `VOIDED`, which is terminal. Voiding runs a three-hop compensation. Because the application record is being withdrawn, the route's `actual_volume_ml` leaves `applied_ml` and returns to `on_hand_ml` and the product's `version` advances — which is precisely why the four-field partition of §2.9 still balances afterwards. Because that usage no longer counts against the area, the area's `seasonal_application_count` decreases by 1, freeing capacity under the seasonal cap. And because the plan may now have no route in `EXECUTED` or `VERIFIED` at all, a parent plan that had already reached `COMPLETED` reverts `COMPLETED → IN_PROGRESS`, clears `completed_at` back to null, and zeroes its cost record — `material_cost_cents`, `labor_cost_cents`, `subtotal_cents`, `admin_fee_cents`, and `total_cost_cents` all return to 0 and `admin_fee_rate` returns to `0.0`. That third hop fires only when no route of the plan remains in `EXECUTED` or `VERIFIED` after the void; if another verified route survives, the plan stays `COMPLETED`. Voiding also decreases the applicator's `assigned_route_count` by 1 and triggers a recomputation of the plan's `estimated_total_ml`.

Release is the gentler exit and is also an `AbatementManager` action. Releasing a route from `PLANNED` advances it `PLANNED → RELEASED` and moves nothing, since nothing had been reserved. Releasing from `COMMITTED` advances `COMMITTED → RELEASED` and gives the reservation back: the route's `estimated_volume_ml` leaves `committed_ml` and returns to `on_hand_ml`, the product's `version` advances, the applicator's `assigned_route_count` decreases by 1, and the plan's `estimated_total_ml` is recomputed. `RELEASED` is terminal, as is `VOIDED`. Routes are listable with optional narrowing by `treatment_plan_id`, by `applicator_id`, by `pesticide_product_id`, and by `status`, and each route is readable individually with both volume variants exposed.

**Completion** closes the plan and is the only moment its cost record is written. An `AbatementManager` advances the plan `IN_PROGRESS → COMPLETED` only when every route of the plan has settled into `VERIFIED`, `VOIDED`, or `RELEASED`, and at least one of them is `VERIFIED`; a plan with a route still `PLANNED`, still `COMMITTED`, or still merely `EXECUTED`, or a plan where every route was voided or released, is refused with `ERR_ROUTES_NOT_SETTLED` (HTTP 409). On success `completed_at` is stamped from the logical clock.

The **cost allocation** considers only the routes of the plan in `VERIFIED`; voided and released routes contribute nothing at all. It proceeds in five pinned steps. First, material cost: for each verified route, divide its `actual_volume_ml` by 1000 to convert millilitres to litres, multiply by that route's product's `cost_cents_per_liter`, and round half up to a whole number of cents — *per route* — then sum those per-route whole-cent figures into `material_cost_cents`. Second, labour: for each verified route multiply its `duration_minutes` by the crew rate of 120 cents per minute, and sum the products into `labor_cost_cents`. Third, `subtotal_cents` is `material_cost_cents` plus `labor_cost_cents`. Fourth, the administrative fee tier is selected **from the subtotal**, before any fee has been added: `admin_fee_rate` is 0.08 when `subtotal_cents` is below 100000 cents, 0.06 when it is below 500000 cents, and 0.045 otherwise. The tier boundaries are half-open on the low side, so a subtotal of exactly 100000 cents selects 0.06 and a subtotal of exactly 500000 cents selects 0.045. Fifth, `admin_fee_cents` is `subtotal_cents` multiplied by `admin_fee_rate`, rounded half up to a whole number of cents, and `total_cost_cents` is `subtotal_cents` plus `admin_fee_cents`. The evaluation order is fixed — subtotal, then rate, then fee, then total. The fee is never re-derived from the total and no fixed-point iteration is performed, even though the tier boundaries happen to be expressed in the same units as the total. Because each route's material cost is rounded independently before summation, route order has no effect on the result.

### 3.10. Public Complaints, Service Levels, and the District's Reporting View

A `Resident` files a **service request** — a mosquito complaint — naming the `service_area_id` the complaint concerns, a `reporter_contact` of 1 to 120 characters holding the complainant's phone or email of record, a `category` that is one of `STANDING_WATER`, `ADULT_ACTIVITY`, `DEAD_BIRD`, or `SPRAY_CONCERN`, a free-text `description` of 1 to 500 characters, and the district-grid coordinates of the reported location as `x_m` and `y_m`. The filer's `X-User-ID` is recorded as `reported_by_user_id`. The complaint opens on two independent axes: `handling_status` is `RECEIVED` and `verification_status` is `UNVERIFIED`, with `priority` at `ROUTINE`, `assigned_applicator_id` null, and `triaged_at`, `due_at`, `resolved_at`, and `resolution_note` all null, and `reopen_count` at 0. The area's `request_total_count` and `request_open_count` each increase by 1.

The two axes are genuinely parallel and must be modelled as such. `handling_status` is the workflow axis, running `RECEIVED → TRIAGED → ASSIGNED → INSPECTED → RESOLVED → CLOSED` with a reopen edge from `RESOLVED` back to `TRIAGED`. `verification_status` is the field-evidence axis, moving from `UNVERIFIED` to either `FIELD_CONFIRMED` or `UNFOUNDED`, advanced only by inspection and reset only by reopening. The evidence axis never gates the workflow axis except at one point — resolution — and the workflow axis never rewrites the evidence axis except at reopening.

An `AbatementManager` triages a new complaint, advancing `RECEIVED → TRIAGED` and supplying the `priority` the office judges appropriate. The supplied value is not necessarily the value stored: the posture floor of §3.6 applies as a floor, so the stored `priority` is the higher-ranked of the value supplied and the floor implied by the area's current `risk_posture`. A complaint triaged as `ROUTINE` in an area sitting at `EMERGENCY` is therefore stored as `URGENT`. Triage stamps `triaged_at` with the logical clock and computes `due_at`.

**Service levels** are measured in hours from `triaged_at`, and they are what the district publishes to its ratepayers: a `ROUTINE` complaint is due 120 hours after triage — five days — a `PRIORITY` complaint 48 hours after triage, and an `URGENT` complaint 24 hours after triage. `due_at` is always measured from the request's *current* `triaged_at`, meaning the most recent triage including one reached by reopening, and never from the instant an escalation happened. When a posture escalation raises a complaint's priority mid-flight, its `due_at` is recomputed against the shorter service level but from the same original `triaged_at`, which is precisely why an escalation can move a due date into the past.

Assignment advances `TRIAGED → ASSIGNED` and is also an `AbatementManager` action, supplying the `assigned_applicator_id`. The referenced applicator must have `status` of `ACTIVE`; assigning to a suspended applicator is refused with `ERR_APPLICATOR_SUSPENDED`.

Field work belongs to the assigned `FieldTech`, matched by comparing `X-User-ID` to `assigned_applicator_id`, with `ERR_NOT_RESOURCE_OWNER` otherwise on every field action. Inspection advances `ASSIGNED → INSPECTED` and may optionally carry a `verification_status`. When it is supplied it must be `FIELD_CONFIRMED` or `UNFOUNDED`, and anything else is `ERR_VALIDATION`; when it is omitted the visit is recorded as inconclusive and the evidence axis stays `UNVERIFIED`. An inconclusive first visit can be upgraded later by a re-inspection, a self-loop that leaves `handling_status` at `INSPECTED` while overwriting `verification_status` on its own axis. On that self-loop the `verification_status` is **mandatory** and must be `FIELD_CONFIRMED` or `UNFOUNDED` — a re-inspection may not blank the evidence axis back out.

Resolution advances `INSPECTED → RESOLVED`, is performed by the same assigned technician, and requires a `resolution_note`. Here the evidence axis finally gates the workflow: a complaint whose `verification_status` is still `UNVERIFIED` cannot be resolved and is refused with `ERR_REQUEST_NOT_VERIFIED` (HTTP 409) until a re-inspection supplies a verdict. Resolution stamps `resolved_at`, stores the note, and moves one case from the area's `request_open_count` to its `request_resolved_count`.

A resolved complaint may be reopened by an `AbatementManager` within 30 days of `resolved_at`, inclusive at the boundary; later than that the request is refused with `ERR_REOPEN_WINDOW_EXPIRED` (HTTP 422). Reopening advances `RESOLVED → TRIAGED`, increases `reopen_count` by 1, resets `verification_status` to `UNVERIFIED` on its own axis, clears `assigned_applicator_id` back to null so the case must be re-assigned, re-stamps `triaged_at` with the logical clock, and recomputes `due_at` from that new triage instant against the **retained** `priority` — reopening never lowers a priority that escalation has raised. It also moves one case back from `request_resolved_count` to `request_open_count`, restoring the four counters exactly to their pre-resolution values, and the cycle `RESOLVED → TRIAGED → ASSIGNED → INSPECTED → RESOLVED` may run again.

Closure ends the case and is an `AbatementManager` action available from two places. Closing from `RESOLVED` advances `RESOLVED → CLOSED` and moves one case from `request_resolved_count` to `request_closed_count`. Closing directly from `RECEIVED` advances `RECEIVED → CLOSED` — the disposition for a duplicate or out-of-district complaint that never warranted triage — and moves one case from `request_open_count` to `request_closed_count`, leaving `verification_status` at `UNVERIFIED` forever. `CLOSED` is terminal. Complaints are listable with optional narrowing by `service_area_id`, by `assigned_applicator_id`, by `handling_status`, and by `priority`, and readable individually with both axes exposed; both the listing and the individual read are available to `Resident` as well as to the district roles.

Finally, the district needs one page it can hand to a board member or a state auditor. The **surveillance report** is a computed read over a service area that takes an optional `as_of_date` and defaults it to the logical clock's calendar date. Nothing is persisted by the read. The report recomputes, live and from current data, the `abundance_index`, the `larval_index`, and the `degree_days` for that date's windows, and it reports **both** infection-rate variants — `mir_provisional` and `mir_confirmed` — side by side, together with `vector_index_provisional` for the same window, so a reader can see exactly how much of the district's risk number is riding on pools that are still on the bench. Alongside those computed figures it echoes back, unchanged, the area's persisted `risk_posture`, `posture_source`, `seasonal_application_count`, and the four complaint counters `request_total_count`, `request_open_count`, `request_resolved_count`, and `request_closed_count`, plus the `as_of_date` that was used.


---

## 4. Endpoint Definitions

Every endpoint is mounted at the root of the API host; there is no shared prefix, and each collection is a top-level path segment. Endpoints that bring a brand-new resource into existence answer **201 Created**; every other successful call — reads, listings, state transitions, stock adjustments, duty-status changes, assessment confirmation, and the clock capability — answers **200 OK**. A successful call returns the affected resource in `data`, except for the listing endpoints, which return an array, and the clock capability, which returns the newly effective instant. Error statuses are per §5.

The table below is deliberately minimal: it fixes the HTTP contract and the authorised roles only. Request payloads, response side effects, preconditions, and the error each precondition raises are specified in the §2 and §3 narratives above.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Admin-only test-driving capability: move the server's logical clock to a supplied instant | `DistrictAdmin` |
| POST | `/service-areas` | Register a district service area | `DistrictAdmin` |
| GET | `/service-areas/{id}` | Read one service area including its derived posture and counters | `DistrictAdmin`, `FieldTech`, `LabAnalyst`, `VectorEcologist`, `AbatementManager` |
| POST | `/service-areas/{id}/sensitive-sites` | Register a protected site (apiary / organic farm / aquaculture / school) | `DistrictAdmin` |
| GET | `/service-areas/{id}/sensitive-sites` | List the protected sites registered in an area | `DistrictAdmin`, `FieldTech`, `LabAnalyst`, `VectorEcologist`, `AbatementManager`, `SensitiveSiteOperator` |
| POST | `/service-areas/{id}/trap-sites` | Register a surveillance trap site inside an area | `DistrictAdmin` |
| GET | `/service-areas/{id}/trap-sites` | List the trap sites of an area | `DistrictAdmin`, `FieldTech`, `LabAnalyst`, `VectorEcologist`, `AbatementManager` |
| GET | `/trap-sites/{id}` | Read one trap site including its season positive counter | `DistrictAdmin`, `FieldTech`, `LabAnalyst`, `VectorEcologist`, `AbatementManager` |
| POST | `/trap-sites/{id}/collections` | Log an adult-mosquito trap collection; the acting technician becomes its recorder | `FieldTech` |
| GET | `/trap-collections` | List trap collections, filterable by trap site, recorder, and status | `DistrictAdmin`, `FieldTech`, `LabAnalyst`, `VectorEcologist`, `AbatementManager` |
| GET | `/trap-collections/{id}` | Read one trap collection | `DistrictAdmin`, `FieldTech`, `LabAnalyst`, `VectorEcologist`, `AbatementManager` |
| POST | `/trap-collections/{id}/transitions` | Drive the trap-collection chain of custody: SUBMIT (the logging `FieldTech`), VOID (`AbatementManager`) | `FieldTech`, `AbatementManager` |
| POST | `/trap-collections/{id}/lab-pools` | Create an arbovirus test pool from a submitted collection | `LabAnalyst` |
| GET | `/lab-pools` | List lab pools, filterable by collection and status | `DistrictAdmin`, `FieldTech`, `LabAnalyst`, `VectorEcologist`, `AbatementManager` |
| GET | `/lab-pools/{id}` | Read one lab pool | `DistrictAdmin`, `FieldTech`, `LabAnalyst`, `VectorEcologist`, `AbatementManager` |
| POST | `/lab-pools/{id}/transitions` | Drive the lab-pool testing machine: START_TEST, RESULT, DISCARD (all `LabAnalyst`) | `LabAnalyst` |
| POST | `/service-areas/{id}/larval-inspections` | Record a larval dip survey (append-only) | `FieldTech` |
| GET | `/service-areas/{id}/larval-inspections` | List the larval inspections of an area | `DistrictAdmin`, `FieldTech`, `LabAnalyst`, `VectorEcologist`, `AbatementManager` |
| POST | `/service-areas/{id}/weather-observations` | Record one day of weather for an area (at most one per date) | `DistrictAdmin`, `FieldTech` |
| GET | `/service-areas/{id}/weather-observations` | List the weather observations of an area | `DistrictAdmin`, `FieldTech`, `LabAnalyst`, `VectorEcologist`, `AbatementManager` |
| POST | `/service-areas/{id}/risk-assessments` | Open a risk assessment, computing the provisional surveillance indices; version-guarded on the area | `VectorEcologist` |
| GET | `/service-areas/{id}/risk-assessments` | List the risk assessments of an area | `DistrictAdmin`, `FieldTech`, `LabAnalyst`, `VectorEcologist`, `AbatementManager` |
| GET | `/risk-assessments/{id}` | Read one risk assessment including both index variants | `DistrictAdmin`, `FieldTech`, `LabAnalyst`, `VectorEcologist`, `AbatementManager` |
| POST | `/risk-assessments/{id}/confirm` | Confirm an OPEN risk assessment, writing the confirmed variants and re-deriving posture | `VectorEcologist` |
| POST | `/pesticide-products` | Add a pesticide product to district stock | `DistrictAdmin` |
| GET | `/pesticide-products/{id}` | Read one product including the four-field inventory partition | `DistrictAdmin`, `FieldTech`, `LabAnalyst`, `VectorEcologist`, `AbatementManager` |
| POST | `/pesticide-products/{id}/adjustments` | Post a stock receipt or write-off; version-guarded on the product | `DistrictAdmin` |
| POST | `/applicators` | Register a licensed applicator / field technician | `DistrictAdmin` |
| GET | `/applicators/{id}` | Read one applicator including duty status and route load | `DistrictAdmin`, `FieldTech`, `LabAnalyst`, `VectorEcologist`, `AbatementManager` |
| POST | `/applicators/{id}/status` | Set an applicator's duty status to ACTIVE or SUSPENDED | `DistrictAdmin` |
| POST | `/treatment-plans` | Draft a treatment plan justified by a risk assessment | `VectorEcologist` |
| GET | `/treatment-plans` | List treatment plans, filterable by area, triggering assessment, and status | `DistrictAdmin`, `FieldTech`, `LabAnalyst`, `VectorEcologist`, `AbatementManager` |
| GET | `/treatment-plans/{id}` | Read one treatment plan including approvals and cost allocation | `DistrictAdmin`, `FieldTech`, `LabAnalyst`, `VectorEcologist`, `AbatementManager` |
| POST | `/treatment-plans/{id}/transitions` | Drive the treatment-plan machine: SUBMIT, REVISE (`VectorEcologist`); APPROVE, RETURN, SCHEDULE, START, SUSPEND, RESUME, COMPLETE, CANCEL (`AbatementManager`) | `VectorEcologist`, `AbatementManager` |
| POST | `/treatment-plans/{id}/routes` | Add a treatment route to a DRAFT or RETURNED plan | `VectorEcologist` |
| GET | `/treatment-routes` | List treatment routes, filterable by plan, applicator, product, and status | `DistrictAdmin`, `FieldTech`, `LabAnalyst`, `VectorEcologist`, `AbatementManager` |
| GET | `/treatment-routes/{id}` | Read one treatment route including both volume variants | `DistrictAdmin`, `FieldTech`, `LabAnalyst`, `VectorEcologist`, `AbatementManager` |
| POST | `/treatment-routes/{id}/transitions` | Drive the treatment-route machine: COMMIT, VERIFY, VOID, RELEASE (`AbatementManager`); EXECUTE (the assigned `FieldTech`) | `AbatementManager`, `FieldTech` |
| POST | `/treatment-plans/{id}/notifications` | Issue a spray notice to a registered protected site of the plan's area | `DistrictAdmin` |
| GET | `/notifications` | List spray notices, filterable by plan, site, and status | `DistrictAdmin`, `FieldTech`, `LabAnalyst`, `VectorEcologist`, `AbatementManager`, `SensitiveSiteOperator` |
| GET | `/notifications/{id}` | Read one spray notice | `DistrictAdmin`, `FieldTech`, `LabAnalyst`, `VectorEcologist`, `AbatementManager`, `SensitiveSiteOperator` |
| POST | `/notifications/{id}/transitions` | Drive the notice delivery machine: SEND, FAIL, REQUEUE, ABANDON, EXPIRE (`DistrictAdmin`); ACKNOWLEDGE (the owning `SensitiveSiteOperator`) | `DistrictAdmin`, `SensitiveSiteOperator` |
| POST | `/service-requests` | File a public complaint against an area | `Resident` |
| GET | `/service-requests` | List service requests, filterable by area, assignee, handling status, and priority | `DistrictAdmin`, `FieldTech`, `LabAnalyst`, `VectorEcologist`, `AbatementManager`, `Resident` |
| GET | `/service-requests/{id}` | Read one service request including both status axes | `DistrictAdmin`, `FieldTech`, `LabAnalyst`, `VectorEcologist`, `AbatementManager`, `Resident` |
| POST | `/service-requests/{id}/transitions` | Drive the service-request machine: TRIAGE, ASSIGN, REOPEN, CLOSE (`AbatementManager`); INSPECT, RESOLVE (the assigned `FieldTech`) | `AbatementManager`, `FieldTech` |
| GET | `/service-areas/{id}/surveillance-report` | Computed read: the area's surveillance indices, posture, application count, and complaint partition | `DistrictAdmin`, `FieldTech`, `LabAnalyst`, `VectorEcologist`, `AbatementManager` |

---

## 5. Error Code Catalogue

Each error is returned in the standard error envelope of §2.2 with its `error_id` in `data`. Trigger conditions are not repeated here — every one of them is specified in the §2 and §3 narratives, next to the rule it enforces.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SELF_APPROVAL` | 403 |
| `ERR_SERVICE_AREA_NOT_FOUND` | 404 |
| `ERR_SENSITIVE_SITE_NOT_FOUND` | 404 |
| `ERR_TRAP_SITE_NOT_FOUND` | 404 |
| `ERR_TRAP_COLLECTION_NOT_FOUND` | 404 |
| `ERR_LAB_POOL_NOT_FOUND` | 404 |
| `ERR_RISK_ASSESSMENT_NOT_FOUND` | 404 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_APPLICATOR_NOT_FOUND` | 404 |
| `ERR_TREATMENT_PLAN_NOT_FOUND` | 404 |
| `ERR_TREATMENT_ROUTE_NOT_FOUND` | 404 |
| `ERR_NOTIFICATION_NOT_FOUND` | 404 |
| `ERR_SERVICE_REQUEST_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_ACTION` | 422 |
| `ERR_STALE_SERVICE_AREA_VERSION` | 412 |
| `ERR_STALE_PRODUCT_VERSION` | 412 |
| `ERR_DUPLICATE_RESOURCE` | 409 |
| `ERR_INVALID_TRANSITION` | 409 |
| `ERR_ASSESSMENT_NOT_OPEN` | 409 |
| `ERR_COLLECTION_NOT_SUBMITTED` | 409 |
| `ERR_COLLECTION_HAS_POOLS` | 409 |
| `ERR_TRIGGER_ASSESSMENT_NOT_CONFIRMED` | 409 |
| `ERR_PLAN_NOT_APPROVED` | 409 |
| `ERR_PLAN_NOT_IN_PROGRESS` | 409 |
| `ERR_NO_COMMITTED_ROUTE` | 409 |
| `ERR_NOTIFICATION_INCOMPLETE` | 409 |
| `ERR_ROUTES_NOT_SETTLED` | 409 |
| `ERR_APPLICATOR_SUSPENDED` | 409 |
| `ERR_REQUEST_NOT_VERIFIED` | 409 |
| `ERR_DUPLICATE_APPROVER` | 409 |
| `ERR_APPLICATOR_LICENSE_INVALID` | 422 |
| `ERR_PRODUCT_METHOD_MISMATCH` | 422 |
| `ERR_AREA_MISMATCH` | 422 |
| `ERR_POSTURE_TOO_LOW` | 409 |
| `ERR_SENSITIVE_SITE_NOT_CLEARED` | 409 |
| `ERR_REENTRY_INTERVAL_VIOLATION` | 409 |
| `ERR_APPLICATOR_ROUTE_CONFLICT` | 409 |
| `ERR_COLLECTION_WINDOW_EXPIRED` | 422 |
| `ERR_NOTIFICATION_LEAD_TIME` | 422 |
| `ERR_ACK_WINDOW_EXPIRED` | 422 |
| `ERR_ACK_WINDOW_OPEN` | 409 |
| `ERR_ROUTE_WINDOW_NOT_OPEN` | 409 |
| `ERR_PLAN_START_TOO_EARLY` | 409 |
| `ERR_REOPEN_WINDOW_EXPIRED` | 422 |
| `ERR_RETEST_LIMIT_EXCEEDED` | 409 |
| `ERR_NOTIFICATION_ATTEMPTS_EXHAUSTED` | 409 |
| `ERR_SEASONAL_LIMIT_EXCEEDED` | 409 |
| `ERR_INSUFFICIENT_INVENTORY` | 409 |
| `ERR_INVENTORY_NEGATIVE` | 422 |

