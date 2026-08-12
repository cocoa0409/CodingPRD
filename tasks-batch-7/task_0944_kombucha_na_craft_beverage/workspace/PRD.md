# Kombucha & Non-Alcoholic Craft Beverage API — Product Requirements Document

## 1. Introduction

A modern kombucha house is three businesses wearing one apron. In the back it is a fermentation plant: living cultures are split, pitched into sanitised tanks, coaxed down a pH curve, dosed with priming sugar, and finally drawn off into kegs, bottles and cans. In the middle it is a regulated food producer: every finished lot must trace back through its blend to the raw tea, sugar and juice that went into it, must carry artwork that a compliance officer has approved against the recipe revision actually used, and must be recallable in minutes when a supplier lot turns out to be bad. At the front it is a merchant with three unrelated demand channels — a self-distributed or wholesale trade book with credit terms and keg deposits, a taproom that pours glasses and fills growlers, and a direct-to-consumer subscription that ships a box every four weeks.

The single fact that binds all three together is the half-percent line. Kombucha keeps fermenting in the container, so a beverage that leaves the brite tank as a non-alcoholic product can arrive at the fill line on the other side of the legal boundary. This platform therefore keeps two different alcohol figures for every batch — one **projected** forward from the end of primary fermentation using planned inputs, one **measured** at the fill from an actual instrument reading — computes them by different formulas, and expects them to disagree. Which side of the line the measured figure lands on decides the label statement that must be printed, whether a taproom customer has to show identification, whether a trade account needs an alcohol licence on file, and whether a subscription box may legally be sent to a particular subscriber. Nothing about that decision is allowed to be implicit.

This document specifies the whole surface: eighteen resource families, twelve state machines (two of which advance on two independent axes at once), seventeen named calculations, a seven-hop recall cascade, six conservation invariants that a forward action and its compensation must leave exactly balanced, and an eighty-rung validation ladder whose relative order is itself part of the contract. The API is deliberately deterministic — a logical clock, not wall-clock time, drives every window and every expiry — so that the same sequence of calls always produces the same bytes.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to every endpoint, without exception, must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the capacity the caller is acting in. If either header is absent, or present but empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The same rejection is issued when `X-User-Role` carries a string that is not one of the seven role names below — an unknown role is treated as no credential at all, not as a permission problem.

The seven roles are `ProductionOperator`, `QaManager`, `ComplianceOfficer`, `SalesRep`, `TaproomStaff`, `Subscriber` and `PlatformAdmin`, spelled exactly as shown.

- A `ProductionOperator` runs the brewhouse: recipes and their revisions, cultures, vessels, raw ingredient lots, batches, the QA log, packaging runs, and keg registration and filling.
- A `QaManager` owns quality dispositions: sending a culture for reverification and recording the laboratory result, the corrective sign-off that rescues an at-risk batch, and the release of a finished lot into saleable stock.
- A `ComplianceOfficer` owns labelling and the recall surface: label revisions and their submission and approval, ingredient-lot quarantine and clearance, finished-lot quarantine clearance, and recalls.
- A `SalesRep` owns the trade side: accounts, shipments, keg deposits and returns, payments, and recall acknowledgements.
- A `TaproomStaff` member runs the taproom: tapping and untapping kegs, growler inspections, and pours.
- A `Subscriber` is a subscription holder acting on their own subscription only.
- A `PlatformAdmin` is an operator superset that may perform every business operation in this document, and additionally owns subscription creation, subscription allocation and allocation shipping, and the logical clock.

When the acting role is not listed among the roles authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

**Identity semantics.** Six of the seven roles carry an opaque identity. When `X-User-Role` is `ProductionOperator`, `QaManager`, `ComplianceOfficer`, `SalesRep`, `TaproomStaff` or `PlatformAdmin`, the `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it — for example as `created_by_user_id` and `started_by_user_id` on a packaging run, `submitted_by_user_id` and `approved_by_user_id` on a label revision, `released_by_user_id` on a finished lot, `recorded_by_user_id` on a QA reading, `last_flagged_reading_by_user_id` on a batch, `inspected_by_user_id` on a taproom fill, or `acknowledged_by_user_id` on a recall notice — but it never compares that value to any entity's `id`.

The seventh role is different. When `X-User-Role` is `Subscriber`, `X-User-ID` is the `id` of the acting `Subscription`. Ownership is therefore checked by comparison: for the pause, resume, skip and cancel operations on a subscription, the target subscription's `id` must equal `X-User-ID`; for an operation aimed at a `SubscriptionAllocation`, the allocation's `subscription_id` must equal `X-User-ID`. A `Subscriber` acting on somebody else's subscription is refused with `ERR_UNAUTHORIZED` (HTTP 403), the same code used for a role that is simply not permitted.

**Segregation of duties is about people, not roles.** Three rules in this system compare `X-User-ID` values directly and fire regardless of which role the caller presents. A label revision may not be approved by the same `X-User-ID` that submitted it. A finished lot may not be released by the same `X-User-ID` that opened the packaging run which produced it. A batch may not be signed off by the same `X-User-ID` that recorded its most recent flagged QA reading. All three raise `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). `PlatformAdmin` is a hierarchical override for the role check only — it does **not** bypass any of these three comparisons.

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

Every list endpoint accepts two optional query parameters, `limit` and `offset`. When `limit` is omitted it defaults to 10; the smallest accepted value is 1 and the largest is 100. When `offset` is omitted it defaults to 0, and the smallest accepted value is 0. A `limit` that is not an integer, is below 1, or is above 100, and an `offset` that is not an integer or is below 0, are all rejected with `ERR_VALIDATION` (HTTP 400).

Unless a specific listing states otherwise, list results are ordered by `created_at` ascending. The one documented exception is the batch QA log, which is ordered by `reading_at` ascending with `created_at` ascending as the tie-break.

The `meta` block of a list response carries `limit` (the effective page size), `offset` (the effective starting index), `total_count` (the number of records matching the filter before pagination is applied) and `has_more` (true when records remain beyond this page).

### 2.4. Resource Identity, Versioning and the Logical Clock

Every resource carries a server-minted `id` that is a UUID string with no type prefix, and a `created_at` timestamp. Timestamps everywhere in this system — `created_at`, `updated_at` and every domain instant such as `pitched_at`, `cip_completed_at`, `packaged_at` or `issued_at` — are rendered as ISO 8601 UTC with exactly three fractional digits and a trailing `Z`, for example `2026-05-01T00:00:00.000Z`. A value the domain describes as a date rather than an instant, such as `best_by_date` or a pause boundary, is normalised to `00:00:00.000Z` on that calendar day. Timestamp comparisons are semantic comparisons of instants, never string comparisons.

Seventeen of the eighteen resource families also carry `updated_at`, refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row. The single exception is `QaReading`: a QA reading is an append-only observation and is never edited, so a reading carries only `id` and `created_at` — it has **no** `updated_at` field and **no** `version` field at all.

The `version` integer described here is the concurrency token. It must not be confused with `recipe_version_number`, which is a domain-level recipe revision counter maintained separately on each `Recipe`, nor with `recipe_version_number_at_pitch` on a `Batch` or `approved_recipe_version_number` on a `LabelApproval`, both of which capture a snapshot of `recipe_version_number` rather than of `version`.

**The logical clock.** Nothing in this system reads wall-clock time. A server-wide logical clock governs every window, expiry, hold period and age calculation, and before it is ever set it reads exactly `2026-05-01T00:00:00Z`. It is moved only by an administrative clock-setting capability, which takes a single field `to_iso8601` and returns `current_utc` together with two counters, `expired_ingredient_lot_count` and `overdue_recall_notice_count`, describing what the move swept up. Time never runs backwards: a supplied instant earlier than the current clock is rejected with `ERR_VALIDATION` (HTTP 400), while a value equal to the current clock is accepted.

Moving the clock has three deterministic sweeps, and they are the reason expiry is stamped by the clock rather than inferred at read time. First, every ingredient lot whose `status` is `AVAILABLE` or `PARTIALLY_CONSUMED` and whose `expiry_date` is strictly before the new clock value moves to `EXPIRED`; the count of such lots is returned as `expired_ingredient_lot_count`. Second, every recall notice whose `status` is `PENDING` and whose `ack_deadline_at` is strictly before the new clock value moves to `OVERDUE`; the count is returned as `overdue_recall_notice_count`, and because an overdue notice is still an open notice, the affected account's `open_recall_notice_count` does not change. Third, `days_past_due`, `late_fee` and `aging_bucket` are re-derived for every shipment in status `DELIVERED`.

### 2.5. Units, Precision, Rounding and Day Arithmetic

Money is dollars carried to exactly 2 decimal places, rounded half up. Volumes are liters carried to exactly 2 decimal places, rounded half up. pH values and ABV percentages are likewise carried to exactly 2 decimal places, rounded half up. Unit counts, day counts and index values are integers. Wherever a calculation below specifies an intermediate rounding step, that step is part of the contract: rounding earlier or later than specified changes the result at the margin and is wrong.

Whole-day arithmetic is calendar-day arithmetic on the UTC date component. Adding a whole number of days to an instant preserves the time of day — adding 90 days to `2026-05-26T09:00:00.000Z` yields `2026-08-24T09:00:00.000Z` — unless the target field is a normalised date, in which case the result is stamped at `00:00:00.000Z`. Where the specification speaks of the *whole days between* two instants A and B, it means the number of complete 86 400-second periods from A to B, with any partial period discarded.

Boundary directions are never approximate in this document. Where a rule says "at or above", the exact value passes; where it says "strictly greater than", the exact value fails. Every threshold below states which side it is strict on, and an implementation that flips one of them will fail the corresponding boundary test even though it looks correct on ordinary inputs.

### 2.6. Stale-View Rejection on Shared Parents

Three write operations in this system attach a child record to a parent that many other children may legitimately attach to at the same time. A batch that has reached `READY_TO_PACKAGE` may feed several packaging runs; a released lot may back many shipment lines; one released lot may supply boxes to many subscriptions. Because a second attachment is a perfectly valid product operation, no state precondition can distinguish it from a client acting on figures it read before somebody else moved them. Optimistic concurrency control is what makes that distinction.

Each of the three operations therefore requires a version token as a **non-optional** input field carrying the client's last observed `version` of the parent row:

1. Adding a source draw to a packaging run (`POST /packaging-runs/{id}/sources`) requires `expected_batch_version`, which must equal the current `version` of the `Batch` named by `batch_id`. If another writer has advanced that batch's `version` since the client last read it, the draw is rejected with `ERR_STALE_VERSION` (HTTP 412) — the client believes liters are still there that have already been drawn.
2. Adding a line to a shipment (`POST /shipments/{id}/lines`) requires `expected_finished_lot_version`, which must equal the current `version` of the `FinishedLot` named by `finished_lot_id`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412); the stale token says the client's view of `on_hand_units` and `reserved_units` predates another reservation.
3. Creating a subscription allocation (`POST /subscription-allocations`) requires `expected_finished_lot_version`, which must equal the current `version` of the target `FinishedLot`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). This applies whether the caller names `finished_lot_id` explicitly or leaves it out and lets the first-expiring-first-out selector choose the lot.

No other endpoint in this system takes a version field, and no other endpoint may reject a request for a version reason. In all three cases the check sits after existence resolution and after the state gate belonging to the *requesting* side of the relationship, and before every business gate that reads the parent's own figures — the exact placement is pinned in the gate ladders of section 2.8.

### 2.7. Path Resolution and the Three Not-Found Families

Path parameters are resolved strictly left to right, and body identifiers are resolved after the path in the order the endpoint declares them. A nested read or action whose outer identifier does not resolve fails on the outer identifier; the inner one is never consulted. Every first path parameter in this API is literally `{id}`.

Which not-found code is returned depends on which part of the plant the missing resource belongs to, and this partition is fixed:

- `ERR_PRODUCTION_RESOURCE_NOT_FOUND` (HTTP 404) covers a missing `Recipe`, `LabelApproval`, `ScobyCulture`, `Vessel`, `IngredientLot`, `Batch` or `BatchIngredientUse`.
- `ERR_PACKAGING_RESOURCE_NOT_FOUND` (HTTP 404) covers a missing `PackagingRun`, `FinishedLot` or `Keg`.
- `ERR_COMMERCIAL_RESOURCE_NOT_FOUND` (HTTP 404) covers a missing `Account`, `Shipment`, `ShipmentLine`, `Subscription`, `SubscriptionAllocation`, `TaproomFill` or `RecallNotice`.

A cross-family request therefore returns two different codes depending on which side is missing. Adding a shipment line names a shipment and a lot: an unknown shipment yields `ERR_COMMERCIAL_RESOURCE_NOT_FOUND`, an unknown lot yields `ERR_PACKAGING_RESOURCE_NOT_FOUND`, and when both are unknown the shipment answers first because it is the path parameter. The same asymmetry applies when a subscription allocation names a subscription (commercial) and a lot (packaging), and when a source draw names a packaging run (packaging) and a batch (production).

### 2.8. The Order in Which a Write is Judged

Where several checks guard one mutating operation, the evaluation order is part of the contract, not an implementation detail: a request that trips more than one rung must return the code belonging to the **earliest** rung it trips. Nine operations have a fully pinned ladder.

**Pitching a batch** (`POST /batches`) is judged in thirteen steps: (1) authentication headers present, else `ERR_UNAUTHENTICATED`; (2) the acting role is `ProductionOperator`, else `ERR_UNAUTHORIZED`; (3) `recipe_id` resolves, else `ERR_PRODUCTION_RESOURCE_NOT_FOUND`; (4) `scoby_culture_id` resolves, else the same code; (5) `vessel_id` resolves, else the same code; (6) field shapes — `pitched_liters` strictly positive, `planned_f2_days` at least 1 and at most 7, and `pitched_at` not later than the logical clock — else `ERR_VALIDATION`; (7) the culture's `state` is `ACTIVE`, else `ERR_INVALID_STATE`; (8) the generation cap — the culture's `generation_number` is strictly below 7, or exactly 7 with a reverification no older than 30 whole days — else `ERR_SCOBY_GENERATION_CAP`; (9) the culture's `vitality_score` is at or above 40, else `ERR_SCOBY_VITALITY_TOO_LOW`; (10) the vessel's `state` is `SANITIZED`, else `ERR_VESSEL_UNAVAILABLE`; (11) the logical clock is at or before `cip_completed_at` plus 72 hours, else `ERR_VESSEL_CIP_EXPIRED`; (12) the requested occupancy interval does not intersect the vessel's retained occupancy interval, else `ERR_VESSEL_UNAVAILABLE`; (13) `pitched_liters` is at or below 90 % of `capacity_liters`, else `ERR_VESSEL_CAPACITY_EXCEEDED`.

**Adding a source draw** (`POST /packaging-runs/{id}/sources`) is judged in ten steps: (1) `ERR_UNAUTHENTICATED`; (2) the acting role is `ProductionOperator`, else `ERR_UNAUTHORIZED`; (3) the run id resolves, else `ERR_PACKAGING_RESOURCE_NOT_FOUND`; (4) `batch_id` resolves, else `ERR_PRODUCTION_RESOURCE_NOT_FOUND`; (5) the run's `status` is `DRAFT` or `SOURCED`, else `ERR_INVALID_STATE`; (6) `expected_batch_version` equals the batch's current `version`, else `ERR_STALE_VERSION`; (7) the batch's `ferment_stage` is `READY_TO_PACKAGE` and its `qa_disposition` is not `NONCONFORMING`, else `ERR_INVALID_STATE`; (8) the batch's `recipe_id` equals the run's `recipe_id`, else `ERR_VALIDATION`; (9) `source_batch_count` is strictly below 4 and `liters_drawn` is at or above 20.0, else `ERR_BLEND_RULE_VIOLATION`; (10) `liters_drawn` is at or below the batch's `remaining_liters`, else `ERR_INSUFFICIENT_BATCH_VOLUME`.

**Starting a packaging run** (`POST /packaging-runs/{id}/start`) is judged in ten steps: (1) `ERR_UNAUTHENTICATED`; (2) the acting role is `ProductionOperator`, else `ERR_UNAUTHORIZED`; (3) the run id resolves, else `ERR_PACKAGING_RESOURCE_NOT_FOUND`; (4) the run's `status` is `DRAFT` or `SOURCED`, else `ERR_INVALID_STATE` — a `DRAFT` run is deliberately admitted by this rung so that the zero-source boundary is reachable, and it then always fails the next one; (5) `source_batch_count` is at least 1, else `ERR_BLEND_RULE_VIOLATION`; (6) every source batch has `ferment_stage` equal to `READY_TO_PACKAGE`, else `ERR_INVALID_STATE`; (7) every source batch has `qa_disposition` equal to `CONFORMING` — the fan-in join — else `ERR_INVALID_STATE`; (8) the label revision's `status` is `APPROVED`, where a `STALE` revision yields `ERR_LABEL_STALE` and a `DRAFT` or `SUBMITTED` one yields `ERR_INVALID_STATE`; (9) the label revision's `approved_recipe_version_number` equals the recipe's current `recipe_version_number`, else `ERR_LABEL_STALE`; (10) the label revision's `pasteurized` equals the run's `pasteurized`, else `ERR_LABEL_CLASS_MISMATCH`.

**Completing a packaging run** (`POST /packaging-runs/{id}/complete`) is judged in seven steps: (1) `ERR_UNAUTHENTICATED`; (2) the acting role is `ProductionOperator`, else `ERR_UNAUTHORIZED`; (3) the run id resolves, else `ERR_PACKAGING_RESOURCE_NOT_FOUND`; (4) the run's `status` is `IN_PROGRESS`, else `ERR_INVALID_STATE`; (5) every source batch has a QA reading whose `reading_type` is `PACKAGING`, so that `packaging_abv_pct` is set, else `ERR_VALIDATION`; (6) the measured lot ABV does not exceed the greatest `projected_abv_pct` across the source batches by more than 0.05, else `ERR_ABV_CLASS_DIVERGENCE`; (7) the lot's measured `abv_class` equals the label revision's `abv_class`, else `ERR_LABEL_CLASS_MISMATCH`.

**Releasing a finished lot** (`POST /finished-lots/{id}/release`) is judged in six steps: (1) `ERR_UNAUTHENTICATED`; (2) the acting role is `QaManager`, else `ERR_UNAUTHORIZED`; (3) the lot id resolves, else `ERR_PACKAGING_RESOURCE_NOT_FOUND`; (4) the lot's `status` is `HELD`, else `ERR_INVALID_STATE`; (5) the logical clock is at or after `packaged_at` plus 48 hours, else `ERR_LOT_HOLD_PERIOD`; (6) the acting `X-User-ID` differs from the packaging run's `created_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. The segregation test depends on stored state, so it is evaluated last, with the business rules — not up at rung 2 with the role check — even though it carries a 403.

**Confirming a shipment** (`POST /shipments/{id}/confirm`) is judged in nine steps: (1) `ERR_UNAUTHENTICATED`; (2) the acting role is `SalesRep`, else `ERR_UNAUTHORIZED`; (3) the shipment id resolves, else `ERR_COMMERCIAL_RESOURCE_NOT_FOUND`; (4) the shipment's `status` is `DRAFT`, else `ERR_INVALID_STATE`; (5) at least one line has `line_status` equal to `ACTIVE`, else `ERR_VALIDATION`; (6) the account's `status` is `ACTIVE` — both `ONBOARDING` and `CREDIT_HOLD` fail here — else `ERR_INVALID_STATE`; (7) every `ACTIVE` line whose lot has `abv_class` `ALCOHOLIC` requires the account's `alcoholic_license_on_file` to be true, else `ERR_ALCOHOLIC_CHANNEL_RESTRICTED`; (8) for a `SELF_DISTRIBUTION` account, `ytd_self_dist_liters` plus this shipment's `total_liters` is at or below 4000.0 liters, else `ERR_SELF_DIST_CEILING_EXCEEDED`; (9) credit exposure is at or below the account's `credit_limit`, else `ERR_CREDIT_LIMIT_EXCEEDED`. Compliance precedes fiscal: both the alcoholic-channel gate and the self-distribution ceiling are settled before the credit test is even computed.

**Pouring a taproom fill** (`POST /taproom-fills/{id}/pour`) is judged in eight steps: (1) `ERR_UNAUTHENTICATED`; (2) the acting role is `TaproomStaff`, else `ERR_UNAUTHORIZED`; (3) the fill id resolves, else `ERR_COMMERCIAL_RESOURCE_NOT_FOUND`; (4) the fill's `fill_status` is `REQUESTED` or `INSPECTED`, else `ERR_INVALID_STATE`; (5) a `CUSTOMER_GROWLER` fill is in `fill_status` `INSPECTED` and the logical clock is at or before `inspected_at` plus 24 hours, else `ERR_GROWLER_INSPECTION_REQUIRED`; (6) the keg's `status` is `ON_TAP`, else `ERR_INVALID_STATE`; (7) when the keg's lot has `abv_class` `ALCOHOLIC`, `customer_birth_date` is present and the customer is at least 21 years old at the logical clock, else `ERR_AGE_VERIFICATION_REQUIRED`; (8) `requested_liters` is at or below the keg's `remaining_liters`, else `ERR_INSUFFICIENT_KEG_VOLUME`.

**Adding a shipment line** (`POST /shipments/{id}/lines`) is judged in nine steps: (1) `ERR_UNAUTHENTICATED`; (2) the acting role is `SalesRep`, else `ERR_UNAUTHORIZED`; (3) the shipment id resolves, else `ERR_COMMERCIAL_RESOURCE_NOT_FOUND`; (4) `finished_lot_id` resolves, else `ERR_PACKAGING_RESOURCE_NOT_FOUND`; (5) the shipment's `status` is `DRAFT`, else `ERR_INVALID_STATE`; (6) `expected_finished_lot_version` equals the lot's current `version`, else `ERR_STALE_VERSION`; (7) the lot's `status` is `RELEASED`, else `ERR_INVALID_STATE`; (8) `units` is strictly positive and `unit_price` is strictly positive, else `ERR_VALIDATION`; (9) the lot's `on_hand_units` minus its `reserved_units` is at or above `units`, else `ERR_INSUFFICIENT_LOT_UNITS`.

**Creating a subscription allocation** (`POST /subscription-allocations`) is judged in eleven steps: (1) `ERR_UNAUTHENTICATED`; (2) the acting role is `PlatformAdmin`, else `ERR_UNAUTHORIZED`; (3) `subscription_id` resolves, else `ERR_COMMERCIAL_RESOURCE_NOT_FOUND`; (4) `finished_lot_id`, when supplied, resolves, else `ERR_PACKAGING_RESOURCE_NOT_FOUND`; (5) the subscription's `status` is `ACTIVE`, else `ERR_INVALID_STATE`; (6) `expected_finished_lot_version` equals the lot's current `version`, else `ERR_STALE_VERSION`; (7) the lot's `status` is `RELEASED`, else `ERR_INVALID_STATE`; (8) the lot's `recipe_id` equals the subscription's `preferred_recipe_id`, else `ERR_VALIDATION`; (9) the lot's `best_by_date` is strictly after the logical clock plus 14 whole days, else `ERR_SHELF_LIFE_TOO_SHORT`; (10) when the lot's `abv_class` is `ALCOHOLIC`, the subscriber is at least 21 years old at the logical clock, else `ERR_AGE_VERIFICATION_REQUIRED`; (11) the lot's `on_hand_units` minus its `reserved_units` is at or above 6, else `ERR_INSUFFICIENT_LOT_UNITS`. Optimistic concurrency sits at rung 6 here — after existence and after the subscription's own state gate, before every lot-side business gate — and the other two concurrency rules use the same relative placement.

**Twelve pairs of rungs are close enough together to be worth stating explicitly.** When both members of a pair are trippable by a single request, the winner is fixed:

| Competing codes | Winner | Where | Why |
| --- | --- | --- | --- |
| `ERR_ABV_CLASS_DIVERGENCE` vs `ERR_LABEL_CLASS_MISMATCH` | `ERR_ABV_CLASS_DIVERGENCE` | completing a packaging run | A measured figure that has run away from the projection is a measurement-integrity problem; the label mismatch it produces is a symptom. |
| `ERR_VESSEL_UNAVAILABLE` vs `ERR_VESSEL_CIP_EXPIRED` | `ERR_VESSEL_UNAVAILABLE` | pitching a batch | Vessel state is a state precondition (rung 10); CIP freshness is temporal (rung 11). |
| `ERR_VESSEL_CIP_EXPIRED` vs `ERR_VESSEL_CAPACITY_EXCEEDED` | `ERR_VESSEL_CIP_EXPIRED` | pitching a batch | Sanitation is a safety rung and outranks the capacity constraint. |
| `ERR_SCOBY_GENERATION_CAP` vs `ERR_SCOBY_VITALITY_TOO_LOW` | `ERR_SCOBY_GENERATION_CAP` | pitching a batch | Lineage depth is a hard compliance cap (rung 8); vitality is a graded health rung (rung 9). |
| `ERR_INVALID_STATE` vs `ERR_CREDIT_LIMIT_EXCEEDED` | `ERR_INVALID_STATE` | confirming a shipment | The account's standing (rung 6) is a state precondition; the credit test (rung 9) is fiscal. |
| `ERR_ALCOHOLIC_CHANNEL_RESTRICTED` vs `ERR_CREDIT_LIMIT_EXCEEDED` | `ERR_ALCOHOLIC_CHANNEL_RESTRICTED` | confirming a shipment | Compliance before fiscal. |
| `ERR_SELF_DIST_CEILING_EXCEEDED` vs `ERR_CREDIT_LIMIT_EXCEEDED` | `ERR_SELF_DIST_CEILING_EXCEEDED` | confirming a shipment | The statutory self-distribution ceiling (rung 8) outranks the commercial credit limit (rung 9). |
| `ERR_GROWLER_INSPECTION_REQUIRED` vs `ERR_AGE_VERIFICATION_REQUIRED` | `ERR_GROWLER_INSPECTION_REQUIRED` | pouring a taproom fill | The container gate (rung 5) is checked before the person gate (rung 7). |
| `ERR_AGE_VERIFICATION_REQUIRED` vs `ERR_INSUFFICIENT_KEG_VOLUME` | `ERR_AGE_VERIFICATION_REQUIRED` | pouring a taproom fill | Age gating is regulatory; volume is inventory. |
| `ERR_LOT_HOLD_PERIOD` vs `ERR_SEGREGATION_OF_DUTIES` | `ERR_LOT_HOLD_PERIOD` | releasing a finished lot | The hold window (rung 5) is evaluated before the segregation test (rung 6), even though the latter carries a 403. |
| `ERR_STALE_VERSION` vs `ERR_INSUFFICIENT_LOT_UNITS` | `ERR_STALE_VERSION` | adding a shipment line, and creating a subscription allocation | A client holding a stale view of the lot is told so before its arithmetic is judged. |
| `ERR_SHELF_LIFE_TOO_SHORT` vs `ERR_INSUFFICIENT_LOT_UNITS` | `ERR_SHELF_LIFE_TOO_SHORT` | creating a subscription allocation | Product safety (rung 9) precedes availability (rung 11). |

### 2.9. The Global Validation Ladder

Beyond the nine per-operation ladders above, the platform evaluates a single system-wide ordering. Its bands run: authentication, then authorisation, then existence, then request shape, then state preconditions, then optimistic concurrency, then compliance and safety, then temporal windows, then referential coherence, then capacity constraints, and finally fiscal limits. Within a band the rungs are numbered, and a lower number always wins over a higher one on the same request. All eighty rungs are listed here with the scope each one guards; the workflow sections in part 3 restate most of them in business context.

**Authentication and authorisation.**

1. `X-User-Role` and `X-User-ID` are both present and non-empty, on every endpoint — otherwise `ERR_UNAUTHENTICATED` (401).
2. `X-User-Role` names one of the seven declared roles, on every endpoint — otherwise `ERR_UNAUTHENTICATED` (401).
3. The acting role appears in the endpoint's authorised-role list, on every endpoint — otherwise `ERR_UNAUTHORIZED` (403).
4. When the acting role is `Subscriber`, `X-User-ID` equals the target `Subscription`'s `id`, or the `subscription_id` of the target `SubscriptionAllocation`. This guards the subscription pause, resume, skip and cancel operations — otherwise `ERR_UNAUTHORIZED` (403).

**Existence, resolved left to right in the path and then in body order.** Every rung in this band returns HTTP 404.

5. `recipe_id` resolves to a `Recipe` — guarding recipe revision, batch pitch, label-revision creation, packaging-run creation, subscription creation and the single-recipe read — otherwise `ERR_PRODUCTION_RESOURCE_NOT_FOUND`.
6. `scoby_culture_id`, or `parent_culture_id` when supplied, resolves to a `ScobyCulture` — guarding culture creation, batch pitch and every culture action — otherwise `ERR_PRODUCTION_RESOURCE_NOT_FOUND`.
7. `vessel_id` resolves to a `Vessel` — guarding batch pitch, CIP start, CIP completion and the single-vessel read — otherwise `ERR_PRODUCTION_RESOURCE_NOT_FOUND`.
8. `ingredient_lot_id` resolves to an `IngredientLot` — guarding ingredient-use recording, ingredient-lot quarantine and ingredient-lot clearance — otherwise `ERR_PRODUCTION_RESOURCE_NOT_FOUND`.
9. `batch_id` resolves to a `Batch` — guarding every batch action and the source draw — otherwise `ERR_PRODUCTION_RESOURCE_NOT_FOUND`.
10. The `BatchIngredientUse` id resolves — guarding the void of a consumption record — otherwise `ERR_PRODUCTION_RESOURCE_NOT_FOUND`.
11. `label_approval_id` resolves to a `LabelApproval` — guarding packaging-run creation and every label-revision action — otherwise `ERR_PRODUCTION_RESOURCE_NOT_FOUND`.
12. The packaging run id resolves — guarding every packaging-run action and the single-run read — otherwise `ERR_PACKAGING_RESOURCE_NOT_FOUND`.
13. `finished_lot_id` resolves to a `FinishedLot` — guarding every finished-lot action, the keg fill, the shipment line and the subscription allocation — otherwise `ERR_PACKAGING_RESOURCE_NOT_FOUND`.
14. The keg id resolves — guarding every keg action and the opening of a taproom fill — otherwise `ERR_PACKAGING_RESOURCE_NOT_FOUND`.
15. `account_id` resolves to an `Account` — guarding shipment creation, keg issue and every account action — otherwise `ERR_COMMERCIAL_RESOURCE_NOT_FOUND`.
16. The shipment id resolves — guarding every shipment action and the single-shipment read — otherwise `ERR_COMMERCIAL_RESOURCE_NOT_FOUND`.
17. The subscription id or the subscription-allocation id resolves — guarding every subscription action, allocation creation and allocation shipping — otherwise `ERR_COMMERCIAL_RESOURCE_NOT_FOUND`.
18. The taproom-fill id or the recall-notice id resolves — guarding growler inspection, the pour and notice acknowledgement — otherwise `ERR_COMMERCIAL_RESOURCE_NOT_FOUND`.

**Request shape and temporal sanity.**

19. Every field the endpoint declares as required is present and of the declared type, on every endpoint — otherwise `ERR_VALIDATION` (400).
20. Every enum-typed field carries one of the members declared for it, on every endpoint — otherwise `ERR_VALIDATION` (400).
21. On every list endpoint, `limit` is an integer between 1 and 100 inclusive and `offset` is at or above 0 — otherwise `ERR_VALIDATION` (400).
22. Quantities are strictly positive wherever they appear: `pitched_liters`, `quantity_used`, `liters_drawn`, `units`, `unit_price`, `requested_liters`, `fill_liters`, `capacity_liters` and `credit_limit`, on every create or draw endpoint carrying the field — otherwise `ERR_VALIDATION` (400).
23. A new logical-clock value is at or after the current logical clock; time never runs backwards — otherwise `ERR_VALIDATION` (400).
24. On a QA reading, `reading_at` is at or after the batch's `pitched_at` and at or before the logical clock — otherwise `ERR_VALIDATION` (400).
25. On a batch pitch, `pitched_at`, when supplied, is at or before the logical clock — otherwise `ERR_VALIDATION` (400).
26. On subscription creation, `subscriber_email` is unique across subscriptions whose `status` is `ACTIVE` or `PAUSED` — otherwise `ERR_VALIDATION` (400).
27. On allocation creation, `cycle_index` is unique within the subscription across allocations whose `status` is `ALLOCATED` or `SHIPPED` — otherwise `ERR_VALIDATION` (400).

**State preconditions.** Every rung in this band returns HTTP 409.

28. A `ScobyCulture` has `state` `ACTIVE` for a pitch, a reverification request or a retirement, and `REVERIFICATION_PENDING` for a reverification result — otherwise `ERR_INVALID_STATE`.
29. A `Vessel` has `state` `SANITIZED` for a pitch, is in `DIRTY` or `SANITIZED` for a CIP start, and is `CIP_IN_PROGRESS` for a CIP completion — otherwise `ERR_VESSEL_UNAVAILABLE`.
30. A `Batch` has the `ferment_stage` the action needs: `F1_ACTIVE` to advance to secondary, `F2_ACTIVE` to complete secondary, `READY_TO_PACKAGE` to be drawn from, and any non-terminal stage to be dumped or to receive a QA reading — otherwise `ERR_INVALID_STATE`. This guards every batch action and the source draw.
31. A `Batch` has `qa_disposition` other than `NONCONFORMING` to advance to secondary, to complete secondary and to be drawn from, and exactly `AT_RISK` to receive a corrective sign-off — otherwise `ERR_INVALID_STATE`.
32. An `IngredientLot` has `status` in `AVAILABLE` or `PARTIALLY_CONSUMED` for a use, in `AVAILABLE`, `PARTIALLY_CONSUMED` or `CONSUMED` for a quarantine, and exactly `QUARANTINED` for a clearance — otherwise `ERR_INVALID_STATE`.
33. A `LabelApproval` has `status` in `DRAFT` or `STALE` for a submission and exactly `SUBMITTED` for an approval — otherwise `ERR_INVALID_STATE`.
34. A `PackagingRun` has `status` in `DRAFT` or `SOURCED` for a source draw and for a start, exactly `IN_PROGRESS` for a completion, and in `DRAFT`, `SOURCED` or `IN_PROGRESS` for an abort — otherwise `ERR_INVALID_STATE`.
35. A `FinishedLot` has `status` exactly `HELD` for a release, in `HELD` or `RELEASED` for a quarantine, exactly `QUARANTINED` for a clearance and for a recall, and exactly `RELEASED` to back a keg fill, a shipment line or an allocation — otherwise `ERR_INVALID_STATE`.
36. A `Keg` has `status` in `IN_STOCK`, `EMPTY` or `RETURNED` for a fill, exactly `FILLED` for a tap and for an issue, exactly `ON_TAP` for an untap and for opening a taproom fill, and exactly `ON_DEPOSIT` for a return — otherwise `ERR_INVALID_STATE`.
37. An `Account` has `status` `ACTIVE` for a shipment confirmation and for a keg issue, and `ONBOARDING` for an activation — otherwise `ERR_INVALID_STATE`.
38. A `Shipment` has `status` exactly `DRAFT` for a line add and for a confirmation, exactly `CONFIRMED` for a delivery, exactly `DELIVERED` for a payment, and in `DRAFT`, `CONFIRMED` or `RECALL_HOLD` for a cancellation — otherwise `ERR_INVALID_STATE`.
39. A `Subscription` has `status` `ACTIVE` for a pause, a skip and an allocation, `PAUSED` for a resume, and in `ACTIVE` or `PAUSED` for a cancellation — otherwise `ERR_INVALID_STATE`.
40. A `TaproomFill` has `fill_status` exactly `REQUESTED` for an inspection and in `REQUESTED` or `INSPECTED` for a pour; a `SubscriptionAllocation` has `status` `ALLOCATED` to be shipped — otherwise `ERR_INVALID_STATE`.
41. A `RecallNotice` has `status` in `PENDING` or `OVERDUE` to be acknowledged — otherwise `ERR_INVALID_STATE`.

**Optimistic concurrency.**

42. `expected_batch_version` equals the batch's current `version` on a source draw — otherwise `ERR_STALE_VERSION` (412).
43. `expected_finished_lot_version` equals the lot's current `version` on a shipment line and on a subscription allocation — otherwise `ERR_STALE_VERSION` (412).

**Compliance and safety.**

44. The culture's `generation_number` is strictly below 7, or exactly 7 with `last_reverified_at` no older than 30 whole days; and a daughter whose `generation_number` would be 8 or more may not be created at all. This guards both the batch pitch and culture creation — otherwise `ERR_SCOBY_GENERATION_CAP` (422).
45. The culture's `vitality_score` is at or above 40 at pitch time — otherwise `ERR_SCOBY_VITALITY_TOO_LOW` (422).
46. The ingredient lot's `expiry_date` is strictly after the logical clock plus 7 whole days; an expiry falling exactly on that boundary is refused. This guards the recording of an ingredient use — otherwise `ERR_INGREDIENT_EXPIRED` (422).
47. The batch reached its effective pH ceiling at a `day_index` inside the inclusive window from 5 through 14, and secondary fermentation was closed at or before `f2_started_at` plus 7 whole days. This guards both the advance to secondary and the completion of secondary — otherwise `ERR_PH_WINDOW_MISSED` (422).
48. On a label submission and on a label approval: `declared_elements` is a superset of `required_elements`, `abv_class` equals the recipe's `intended_abv_class`, and `pasteurized` is true whenever the recipe's `pasteurization_required` is true — otherwise `ERR_LABEL_CLASS_MISMATCH` (422).
49. The approving `X-User-ID` differs from `submitted_by_user_id` on a label approval — otherwise `ERR_SEGREGATION_OF_DUTIES` (403).
50. The packaging run's label revision is `APPROVED` and its `approved_recipe_version_number` equals the recipe's current `recipe_version_number`, checked when the run is started — otherwise `ERR_LABEL_STALE` (409).
51. The measured lot ABV does not exceed the greatest `projected_abv_pct` across the source batches by more than 0.05 percentage points; a divergence of exactly 0.05 is accepted. Checked when a run is completed — otherwise `ERR_ABV_CLASS_DIVERGENCE` (422).
52. The lot's measured `abv_class` equals the label revision's `abv_class`, and the label revision's `pasteurized` equals the run's `pasteurized`. This guards both the start and the completion of a packaging run — otherwise `ERR_LABEL_CLASS_MISMATCH` (422).
53. The releasing `X-User-ID` differs from the packaging run's `created_by_user_id` — otherwise `ERR_SEGREGATION_OF_DUTIES` (403).
54. The signing-off `X-User-ID` differs from the batch's `last_flagged_reading_by_user_id`, and `qa_signoff_count` is 0 — otherwise `ERR_SEGREGATION_OF_DUTIES` (403).
55. When any `ACTIVE` line's lot, or the keg's lot, carries `abv_class` `ALCOHOLIC`, the account has `alcoholic_license_on_file` true. This guards both the shipment confirmation and the keg issue — otherwise `ERR_ALCOHOLIC_CHANNEL_RESTRICTED` (422).
56. A `CUSTOMER_GROWLER` fill has passed inspection and the logical clock is at or before `inspected_at` plus 24 hours, checked at the pour — otherwise `ERR_GROWLER_INSPECTION_REQUIRED` (422).
57. When the poured lot's `abv_class` is `ALCOHOLIC`, `customer_birth_date` is present and the customer is at least 21 years old at the logical clock — otherwise `ERR_AGE_VERIFICATION_REQUIRED` (403).
58. When the allocated lot's `abv_class` is `ALCOHOLIC`, the subscriber is at least 21 years old at the logical clock, measured from `subscriber_birth_date` — otherwise `ERR_AGE_VERIFICATION_REQUIRED` (403).
59. The lot's `best_by_date` is strictly after the logical clock plus 14 whole days, checked when an allocation is created — otherwise `ERR_SHELF_LIFE_TOO_SHORT` (422).

**Temporal windows.**

60. The logical clock is at or before the vessel's `cip_completed_at` plus 72 hours at pitch time; the exact 72-hour instant is still valid — otherwise `ERR_VESSEL_CIP_EXPIRED` (422).
61. The half-open interval running from the batch's `pitched_at` up to but excluding its `occupancy_end_at` does not intersect the vessel's retained half-open occupancy interval; a pitch starting exactly at the retained end is accepted — otherwise `ERR_VESSEL_UNAVAILABLE` (409).
62. The logical clock is at or after `packaged_at` plus 48 hours at release time; the exact 48-hour instant is already releasable — otherwise `ERR_LOT_HOLD_PERIOD` (422).
63. When `last_untapped_at` is set, the logical clock is strictly after `last_untapped_at` plus 15 minutes at tap time; a re-tap exactly on the buffer boundary is refused — otherwise `ERR_KEG_RETAP_BUFFER` (422).
64. The requested closed pause interval spans at or below 60 days counting both ends, and does not intersect any interval already recorded in `pause_windows`; two closed intervals that merely touch at an endpoint do intersect — otherwise `ERR_PAUSE_WINDOW_CONFLICT` (409).

**Referential coherence.** Every rung in this band returns HTTP 400 under `ERR_VALIDATION`.

65. On a source draw, the batch's `recipe_id` equals the packaging run's `recipe_id`.
66. On packaging-run creation, the label revision's `recipe_id` equals the run's `recipe_id`.
67. On allocation creation, the lot's `recipe_id` equals the subscription's `preferred_recipe_id`.
68. On a keg fill, the lot's `format` is `KEG` and `fill_liters` is at or below the keg's `capacity_liters`.

**Capacity and constraint.**

69. `pitched_liters` is at or below `capacity_liters` multiplied by 90 and divided by 100; a fill of exactly 90 % of capacity is accepted — otherwise `ERR_VESSEL_CAPACITY_EXCEEDED` (422).
70. `source_batch_count` is strictly below 4 before the draw, `liters_drawn` is at or above 20.0 liters, and a run being started has at least one draw. This guards both the source draw and the run start — otherwise `ERR_BLEND_RULE_VIOLATION` (422).
71. `liters_drawn` is at or below the batch's `remaining_liters` — otherwise `ERR_INSUFFICIENT_BATCH_VOLUME` (422).
72. `quantity_used` is at or below the ingredient lot's `quantity_available` — otherwise `ERR_VALIDATION` (400).
73. `quarantine_clearance_count` is strictly below 1 when a lot is cleared out of quarantine — otherwise `ERR_QUARANTINE_CLEARANCE_CAP` (422).
74. `skips_used_this_year` is strictly below 3 and no allocation for the current `cycle_index` is still `ALLOCATED` — otherwise `ERR_SUBSCRIPTION_SKIP_CAP` (422).
75. On opening a taproom fill, `requested_liters` is at or above 0.1 liters and, for either growler container type, at or below 1.9 liters — otherwise `ERR_VALIDATION` (400).
76. At the pour, `requested_liters` is at or below the keg's `remaining_liters`; a pour of exactly the remainder is accepted — otherwise `ERR_INSUFFICIENT_KEG_VOLUME` (422).
77. The lot's `on_hand_units` minus its `reserved_units` is at or above the units requested — the line's `units` for a shipment line, and 6 for a subscription box — otherwise `ERR_INSUFFICIENT_LOT_UNITS` (422).

**Fiscal, evaluated last.**

78. For a `SELF_DISTRIBUTION` account, `ytd_self_dist_liters` plus this shipment's `total_liters` is at or below 4000.0 liters; exactly 4000.0 is accepted — otherwise `ERR_SELF_DIST_CEILING_EXCEEDED` (422).
79. Credit exposure is at or below the account's `credit_limit`; exactly equal is accepted — otherwise `ERR_CREDIT_LIMIT_EXCEEDED` (402).
80. A payment's `amount` equals the shipment's `subtotal` plus its `late_fee`, both rounded to 2 decimals — otherwise `ERR_VALIDATION` (400).

### 2.10. The Half-Percent Line

One threshold governs the regulatory identity of everything this plant makes. An alcohol-by-volume figure **at or above 0.50 %** classifies the liquid as `ALCOHOLIC`; a figure **strictly below 0.50 %** classifies it as `NON_ALCOHOLIC`. Exactly 0.50 % is `ALCOHOLIC`. The comparison is always made on the figure *after* it has been rounded half up to 2 decimal places, never on an unrounded intermediate.

The classification is applied at two different moments, to two different numbers, computed by two different formulas, and the two are allowed to disagree. Before the fill, a batch carries `projected_abv_pct` — a forward-looking estimate that models a secondary fermentation which has not happened yet — and the class implied by it is stored as `projected_abv_class`. At the fill, the finished lot carries `measured_abv_pct`, taken from an actual instrument reading, and the class implied by *that* is stored as the lot's `abv_class`. The lot's `abv_class` is the one with legal effect. The projection's only jobs are to let a compliance officer plan the artwork and to give the divergence check something to compare against.

Four downstream consequences follow from a lot being `ALCOHOLIC` rather than `NON_ALCOHOLIC`, and each is enforced at a different place. The label revision must carry the alcoholic element set rather than the non-alcoholic one. A taproom pour requires a birth date and a customer of at least 21 years. A subscription box requires a subscriber of at least 21 years. A trade shipment, and a keg issued on deposit, require the receiving account to have `alcoholic_license_on_file` set to true.

### 2.11. Conservation of Liquid, Units, Deposits and Flags

Six quantities in this system must balance exactly at all times. Each pairs a forward action with a compensating action, and the compensation must leave the quantity exactly where the forward action found it — not approximately, and not with a rounding remainder parked somewhere.

1. **Finished-goods units.** For every finished lot, `units_produced` always equals `on_hand_units` plus `shipped_units` plus `poured_units` plus `destroyed_units`. Alongside that, `reserved_units` is at all times at or below `on_hand_units`. Reservation is a claim on units that are still on hand, not a fifth bucket, so adding a line and confirming a shipment, then cancelling that shipment, must move exactly zero units between the four conserved buckets.
2. **Batch liters.** For every batch, `pitched_liters` always equals `remaining_liters` plus `drawn_liters` plus `loss_liters`. Drawing liters into a packaging run and then aborting that run must restore the batch to its exact prior split.
3. **Keg deposit dollars.** For every account, `keg_deposit_balance` equals 45.00 dollars multiplied by the number of kegs currently held by that account with `deposit_state` `CHARGED`. A second, stronger condition also holds: 45.00 multiplied by `kegs_charged_lifetime` equals `keg_deposit_balance` plus `deposit_refunded_total` plus `deposit_forfeited_total`. That side condition is what catches a partial refund whose forfeited remainder was silently dropped.
4. **QA flags.** For every batch, `flagged_reading_count` equals the number of QA readings on that batch whose `flagged` is true, and the counter is non-decreasing for the life of the batch. The corrective sign-off is the only route back to `CONFORMING`, and it deliberately does **not** decrement the counter. An implementation that instead derives `qa_disposition` from a time window or from the latest reading alone will silently re-enter `CONFORMING` after one clean reading; that drift is invisible on `qa_disposition` itself and shows up only as `flagged_reading_count` disagreeing with the QA log.
5. **Ingredient quantities.** For every raw ingredient lot, `quantity_received` equals `quantity_available` plus the sum of `quantity_used` over every consumption record against that lot whose `voided` is false. Recording a use and then voiding it must restore the lot exactly.
6. **Self-distributed liters.** For every account, `ytd_self_dist_liters` equals the sum of `total_liters` over that account's shipments whose `status` is `DELIVERED` or `PAID`, where the account's `channel` is `SELF_DISTRIBUTION` and the shipment's `delivered_on_date` falls in the same UTC calendar year as the logical clock. This one has no compensating action: a delivery is not reversible, so the ledger is always re-derived and never adjusted by increments alone.

### 2.12. Traceability and the Three Cascades

Three named cascades run in this system. Every hop is caused by the hop before it, and each cascade also has legs that deliberately do **not** fire — those exclusions are as much a part of the contract as the hops themselves.

**The ingredient recall cascade** is seven hops deep and begins when a compliance officer quarantines a raw ingredient lot.

- *Hop 1.* The `IngredientLot` moves from `AVAILABLE`, `PARTIALLY_CONSUMED` or `CONSUMED` to `QUARANTINED`, and the status it held immediately before is recorded in `pre_quarantine_status`.
- *Hop 2.* Every `Batch` reachable through a consumption record whose `voided` is false, and whose `ferment_stage` is `F1_ACTIVE`, `F2_ACTIVE` or `READY_TO_PACKAGE`, has its `qa_disposition` set to `NONCONFORMING`. Does not fire: a consumption record whose `voided` is true does not reach its batch at all, and a batch already in `PACKAGED` or `DUMPED` keeps whatever `qa_disposition` it had.
- *Hop 3.* Every `PackagingRun` whose `status` is `COMPLETED` and which names one of the hop-2 batches in `source_draws` moves to `RECALL_FLAGGED`. Does not fire: runs in `ABORTED` are skipped because they emitted no lot, and runs in `DRAFT`, `SOURCED` or `IN_PROGRESS` are skipped by this cascade — they are stopped instead by the `CONFORMING` fan-in gate the next time somebody tries to start them.
- *Hop 4.* The `FinishedLot` of each newly `RECALL_FLAGGED` run, when its `status` is `HELD` or `RELEASED`, moves to `QUARANTINED` with `pre_quarantine_status` recorded. Does not fire: lots already `QUARANTINED`, `RECALLED` or `DEPLETED` are skipped.
- *Hop 5.* For each newly quarantined lot, three unwindings happen. (a) Every `ShipmentLine` with `line_status` `ACTIVE` sitting on a shipment whose `status` is `DRAFT` or `CONFIRMED` moves to `line_status` `RECALLED`, and the lot's `reserved_units` is decreased by that line's `units`; a `CONFIRMED` shipment additionally moves to `RECALL_HOLD`, while a `DRAFT` shipment keeps `status` `DRAFT` even though its exposed lines move. (b) Every `SubscriptionAllocation` whose `status` is `ALLOCATED` moves to `REVERSED` with `reversal_reason` `LOT_QUARANTINED`, the lot's `reserved_units` is decreased by that allocation's `units`, and the subscription's `credit_balance` is increased by the allocation's `charge_amount`. (c) Every `Keg` whose `status` is `FILLED` from that lot moves to `EMPTY` with `remaining_liters` 0, and the lot's `destroyed_units` is increased by 1. Does not fire: lines on shipments in `DELIVERED`, `PAID` or `CANCELLED` are untouched; allocations already `SHIPPED` or `REVERSED` are untouched; kegs in `ON_TAP`, `ON_DEPOSIT`, `RETURNED` or `SCRAPPED` are untouched.
- *Hop 6.* One `RecallNotice` in `status` `PENDING` is created for each account-and-lot pair that has any exposure, where exposure means either a line with `line_status` `ACTIVE` or `RECALLED` on any shipment of that account referencing the lot, or a keg from that lot held by the account with `deposit_state` `CHARGED`. Does not fire: an account that already holds a `PENDING` notice for the same lot does not receive a second one.
- *Hop 7.* Each affected account's `open_recall_notice_count` is recomputed as the number of that account's recall notices whose `status` is `PENDING` or `OVERDUE`.

Hops 5 through 7 also run on their own when a compliance officer or QA manager quarantines a finished lot directly, and hops 6 and 7 run again when a quarantined lot is recalled.

**The recipe revision cascade** is four hops deep and begins when a recipe is revised.

- *Hop 1.* The recipe's `recipe_version_number` is incremented by 1.
- *Hop 2.* Every `LabelApproval` of that recipe whose `status` is `APPROVED` moves to `STALE` with `stale_reason` `RECIPE_REVISED`, and the recipe's `active_label_approval_id` is set to null.
- *Hop 3.* Every `PackagingRun` whose `status` is `DRAFT` or `SOURCED` and whose `label_approval_id` names a now-stale revision moves to `ABORTED` — an in-flight run may not print a stale label. Does not fire: runs already `COMPLETED` keep their status, because the lot is already printed and released against the older revision; runs in `IN_PROGRESS` also keep their status, because the fill is physically under way, and they are instead stopped at completion time by the label-version gate.
- *Hop 4.* For each run aborted by hop 3, every source draw is returned — the batch's `drawn_liters` is decreased and its `remaining_liters` increased by the drawn liters, and the batch's `version` is incremented.

**The lot re-allocation cascade** is three hops deep and begins when a quarantined finished lot is cleared.

- *Hop 1.* The lot's `status` moves from `QUARANTINED` back to whatever `pre_quarantine_status` holds, and `quarantine_clearance_count` is incremented by 1.
- *Hop 2.* Every `SubscriptionAllocation` that was reversed with `reversal_reason` `LOT_QUARANTINED` and whose `reallocation_attempt_count` is strictly below 2 returns to `ALLOCATED` with `reallocation_attempt_count` incremented by 1, and the lot's `reserved_units` is increased by that allocation's `units`. Does not fire: allocations reversed with `reversal_reason` `LOT_RECALLED` or `SUBSCRIPTION_CANCELLED` are never re-instated, and an allocation whose `reallocation_attempt_count` already equals 2 stays `REVERSED`.
- *Hop 3.* For each re-instated allocation, the subscription's `credit_balance` is decreased by that allocation's `charge_amount`, undoing the credit granted when it was reversed.

Shipment lines set to `RECALLED` are **not** restored by this cascade; a sales representative must open a new shipment. Clearing a raw ingredient lot out of quarantine likewise restores only the ingredient lot itself — the batches, packaging runs and finished lots that its original cascade touched are each cleared on their own.

## 3. Business Logic & Workflows

### 3.1. Recipes, Revisions and the Label Regime

Everything begins with a recipe. A `ProductionOperator` (or a `PlatformAdmin`) registers one with a human-readable `name`, a `style` drawn from `KOMBUCHA`, `JUN`, `WATER_KEFIR`, `HOP_TONIC` and `BOTANICAL_SODA`, a recipe-specific `target_ph_ceiling`, the planned durations `planned_f1_days` and `planned_f2_days` in whole days, a starting gravity `base_gravity_brix` in degrees Brix, and the class the brewer intends to sell under, `intended_abv_class`, which is either `NON_ALCOHOLIC` or `ALCOHOLIC`. Two further inputs are optional: `f2_added_sugar_g_per_l`, the grams of priming sugar per liter dosed at secondary fermentation, which defaults to 0, and `pasteurization_required`, which defaults to false and, when true, forces every packaging run of the recipe to be flash-pasteurized. A newly registered recipe has `recipe_version_number` set to 1 and `active_label_approval_id` set to null.

The recipe-specific ceiling does not stand alone. The **effective pH ceiling** used by the QA log is the lower of the recipe's `target_ph_ceiling` and the plant-wide primary-fermentation ceiling of 3.50 — a recipe may be stricter than the house rule but never looser. A recipe's `planned_f2_days` may never exceed 7 days, the plant's hard limit on secondary fermentation.

Revising a recipe is a deliberately disruptive act. A revision takes an optional `change_note`, increments `recipe_version_number` by 1, and then runs the four-hop recipe revision cascade described in section 2.12: every `APPROVED` label revision of that recipe drops to `STALE` with `stale_reason` `RECIPE_REVISED`, `active_label_approval_id` is nulled, every packaging run of that recipe still in `DRAFT` or `SOURCED` against a now-stale revision is driven to `ABORTED`, and each aborted run hands its drawn liters back to its source batches. Runs already `COMPLETED` are left alone; runs in `IN_PROGRESS` are also left alone and are caught later, at completion, by the label-version gate. The recipe's own `version` also increments by 1, as it does on any mutation.

**Label artwork lives on its own object with its own lifecycle.** A `ComplianceOfficer` opens a revision by naming the `recipe_id` it is drawn against, the `abv_class` regime the artwork carries, whether the artwork carries the pasteurization statement in `pasteurized`, and `declared_elements`, the list of element codes the submitter claims the artwork actually shows. The server immediately computes `required_elements` from the revision's own `abv_class` and `pasteurized` fields and nothing else. Six element codes are always required: `PRODUCT_NAME`, `NET_CONTENTS`, `INGREDIENTS`, `PRODUCER_ADDRESS`, `LOT_CODE` and `BEST_BY`. When `abv_class` is `NON_ALCOHOLIC`, two more are added — `NON_ALCOHOLIC_STATEMENT` and `CONTAINS_LESS_THAN_HALF_PERCENT_ALCOHOL`; when it is `ALCOHOLIC`, three different ones are added instead — `ALCOHOL_CONTENT_STATEMENT`, `GOVERNMENT_WARNING` and `AGE_RESTRICTED`. Then, when `pasteurized` is true, `PASTEURIZED_STATEMENT` is added; when it is false, two are added instead — `KEEP_REFRIGERATED` and `LIVE_CULTURES`. A non-alcoholic pasteurized revision therefore requires nine codes and a raw alcoholic revision requires eleven. The revision opens in `status` `DRAFT`.

Submission moves a revision from `DRAFT` to `SUBMITTED`, and the same operation moves a `STALE` revision back to `SUBMITTED`. In both cases `required_elements` is re-evaluated first — for a stale revision it is recomputed against the recipe's current fields — and `declared_elements` must be a superset of it: every required code must be present, extra codes are harmless, and a shortfall is refused with `ERR_LABEL_CLASS_MISMATCH`. A successful submission records the acting `X-User-ID` in `submitted_by_user_id` and clears `stale_reason` back to null.

Approval is where segregation of duties bites. A `SUBMITTED` revision is approved only when the acting `X-User-ID` differs from `submitted_by_user_id` — the same person may not both submit and approve, and a violation is `ERR_SEGREGATION_OF_DUTIES` — and only when the revision's `abv_class` matches the recipe's `intended_abv_class` and its `pasteurized` is true whenever the recipe's `pasteurization_required` is true, both of which are refused with `ERR_LABEL_CLASS_MISMATCH` otherwise. On success the revision moves `SUBMITTED → APPROVED`, `approved_recipe_version_number` captures the recipe's `recipe_version_number` at that instant, `approved_by_user_id` records the approver and `approved_at` the logical clock, the recipe's `active_label_approval_id` is pointed at this revision, and any *other* revision of the same recipe that was `APPROVED` is pushed to `STALE` with `stale_reason` `RECIPE_REVISED`. Only one approved artwork per recipe survives at a time.

The `stale_reason` enumeration has exactly one non-null member, `RECIPE_REVISED`; it is null on every revision that is not stale. The full lifecycle is `DRAFT → SUBMITTED → APPROVED → STALE → SUBMITTED → APPROVED`, and there is no terminal state — a revision can be re-submitted and re-approved indefinitely as the recipe evolves.

### 3.2. Culture Lineage and Vitality

A SCOBY is a living asset with a measurable decline, and this system models that decline as an arithmetic score rather than a status field. A `ProductionOperator` propagates a culture by giving it a `label`. When `parent_culture_id` is omitted the new culture is a **founder** and its `generation_number` is 1. When `parent_culture_id` is supplied, the parent must exist and its `state` must be `ACTIVE`, and the daughter's `generation_number` is the parent's plus 1. Lineage depth is capped at 7: a daughter whose `generation_number` would come out at 8 or more is refused outright with `ERR_SCOBY_GENERATION_CAP`. Every new culture starts with `pitch_count` 0, `reverification_count` 0, `last_reverified_at` null, `retire_reason` null and `state` `ACTIVE`.

The **vitality score** is computed from the culture's own history, always using the values as they stand *after* whatever mutation triggered the recomputation. Start from 100. Subtract 6 for each pitch counted in `pitch_count`. Subtract 4 for each generation beyond the first, that is, for `generation_number` minus 1. Add 15 for each passed reverification counted in `reverification_count`. Clamp the result into the closed range 0 through 100, so a computed value below 0 becomes 0 and a value above 100 becomes 100. The stored `vitality_score` is integer-valued. Worked through: a third-generation culture with nine pitches and no reverifications scores 100 minus 54 minus 8 plus 0, which is 38 — below the floor. The same culture after one passed reverification scores 100 minus 0 minus 8 plus 15, which is 107, clamped to 100.

The floor is 40. A culture whose `vitality_score` is at or above 40 may be pitched; strictly below 40 the pitch is refused with `ERR_SCOBY_VITALITY_TOO_LOW`. There is deliberately no automatic retirement at that floor — a worn-out culture stays `ACTIVE` and simply refuses every further pitch, and an operator must retire it explicitly. Each accepted pitch increments `pitch_count` by 1, recomputes `vitality_score` on the new count, and bumps the culture's `version` by 1; the culture stays in `ACTIVE`, which is why this is a self-loop rather than a transition.

Reverification is the only way back up. A `QaManager` sends an `ACTIVE` culture for laboratory work, moving it `ACTIVE → REVERIFICATION_PENDING` and bumping its `version`. The laboratory result carries a single field `outcome`. On `PASS` the culture returns `REVERIFICATION_PENDING → ACTIVE`, `reverification_count` is incremented by 1, `pitch_count` is reset to 0 **before** the score is recomputed, and `last_reverified_at` is stamped with the logical clock. Because the reset lands first and the bonus has already been counted, the same lineage history yields a strictly higher score after a pass than the post-pitch recomputation would have given. On `FAIL` the culture moves `REVERIFICATION_PENDING → CONTAMINATED`, `retire_reason` is set to `CONTAMINATION`, and a two-hop cascade fires: every batch of that culture whose `ferment_stage` is `F1_ACTIVE`, `F2_ACTIVE` or `READY_TO_PACKAGE` has its `qa_disposition` set to `NONCONFORMING`, and every packaging run in `DRAFT`, `SOURCED` or `IN_PROGRESS` that draws on one of those batches is driven to `ABORTED` with its drawn liters returned. Batches already `PACKAGED` or `DUMPED` are **not** re-dispositioned.

A pass has a shelf life of its own. A culture sitting exactly at generation 7 — the cap — may only be pitched when `last_reverified_at` is non-null and the logical clock is at or before that instant plus 30 whole days, inclusive of the exact thirtieth day. Past that, the pitch is refused with `ERR_SCOBY_GENERATION_CAP`, the same code the creation cap uses. Cultures below generation 7 are not subject to the reverification recency test at all.

Manual retirement moves an `ACTIVE` culture to `RETIRED`, but only when no batch of that culture is currently in `ferment_stage` `F1_ACTIVE` or `F2_ACTIVE`. The caller may supply `retire_reason` as one of `OPERATOR`, `VITALITY` or `GENERATION_CAP`; when it is omitted the reason defaults to `OPERATOR`. `RETIRED` and `CONTAMINATED` are both terminal — a culture in either state can never be pitched, reverified or retired again.

### 3.3. Vessels, Sanitation and Occupancy

A fermentation vessel is registered with a stencilled `code` and a nominal `capacity_liters`, and it enters the world in `state` `DIRTY`. Its cycle is `DIRTY → CIP_IN_PROGRESS → SANITIZED → OCCUPIED → DIRTY`, with one extra edge that closes the loop the other way.

Starting a clean-in-place cycle is accepted from `DIRTY` and also from `SANITIZED`; either way the vessel moves to `CIP_IN_PROGRESS`, `cip_started_at` is stamped with the logical clock and `cip_completed_at` is cleared to null. That second edge, from `SANITIZED` back into `CIP_IN_PROGRESS`, is the **re-sanitise** path and it is the only way to refresh an expired sanitation window — there is no automatic decay from `SANITIZED` to `DIRTY`, so a vessel whose sanitation has gone stale still reads `SANITIZED` and must be washed again explicitly. Completing the cycle moves `CIP_IN_PROGRESS → SANITIZED` and stamps `cip_completed_at`; sanitation is then valid for 72 hours measured from that instant, inclusive of the exact 72-hour mark.

Occupancy is an interval, not a flag. When a batch is pitched into a vessel the vessel moves `SANITIZED → OCCUPIED`, `current_batch_id` mirrors the new batch, `occupancy_start_at` takes the batch's pitch instant as an **inclusive** start, and `occupancy_end_at` takes the batch's own computed occupancy end as an **exclusive** end. When the batch later completes secondary fermentation, or is dumped, the vessel returns `OCCUPIED → DIRTY` and `current_batch_id` is cleared to null — but `occupancy_start_at` and `occupancy_end_at` are **retained**. They are kept precisely so that a later back-dated pitch can be tested against them.

That test matters because a pitch may carry an explicit `pitched_at` that is earlier than now. The interval the new batch wants, running from its `pitched_at` up to but excluding its `occupancy_end_at`, must not intersect the interval the vessel has retained. Both intervals are half-open, so a new pitch whose `pitched_at` falls exactly on the retained `occupancy_end_at` **is** accepted; any genuine overlap is refused with `ERR_VESSEL_UNAVAILABLE`. Back-dating is what makes this reachable at all: a freed and re-sanitised vessel reads `SANITIZED`, so the state gate passes, and only the interval arithmetic can turn the pitch away.

### 3.4. Receiving Ingredients and Pitching a Batch

Raw materials arrive as lots. A lot carries an `ingredient_type` drawn from `TEA`, `SUGAR`, `CULTURE_NUTRIENT`, `JUICE`, `BOTANICAL` and `HOPS`, the supplier's printed `supplier_lot_code`, a `received_on_date`, an `expiry_date`, and `quantity_received` expressed in the material's native unit — kilograms for solids, liters for liquids. On receipt `status` is `AVAILABLE`, `quantity_consumed` is 0, `quantity_available` equals `quantity_received`, `quarantine_cleared_count` is 0 and `pre_quarantine_status` is null. `quantity_available` is always `quantity_received` less `quantity_consumed`, and `quantity_consumed` is always the sum of `quantity_used` over the lot's non-voided consumption records.

Pitching a batch is the busiest write in the system. The operator supplies a `batch_code`, the `recipe_id`, the `scoby_culture_id` to pitch from, the `vessel_id` to occupy, the `pitched_liters` of sweet tea charged in, and `planned_f2_days` for this particular batch, which must be at least 1 and at most 7 days. Two inputs are optional: `f2_added_sugar_g_per_l`, defaulting to 0, and `pitched_at`, which defaults to the logical clock and may never be later than it. The thirteen-rung ladder in section 2.8 governs the order in which the pitch is judged; in business terms it checks the culture before the vessel, lineage before health, and sanitation before capacity.

Two of those rungs deserve their numbers restated in context. A vessel may only be charged to 90 % of its nominal capacity — a headspace allowance of 10 % is reserved for the ferment — so `pitched_liters` must be at or below `capacity_liters` multiplied by 90 and divided by 100. A fill of exactly 90 % is accepted; anything strictly greater is `ERR_VESSEL_CAPACITY_EXCEEDED`. And the vessel's sanitation must still be inside its 72-hour window, measured from `cip_completed_at`; the exact 72-hour instant is still good, and past it the pitch is `ERR_VESSEL_CIP_EXPIRED`.

On success the batch is born with `ferment_stage` `F1_ACTIVE` and `qa_disposition` `PENDING`, the two axes it will advance along independently. `pitched_at` is stamped, `recipe_version_number_at_pitch` captures the recipe's `recipe_version_number` as it stands at that moment, `remaining_liters` is set to `pitched_liters` while `drawn_liters` and `loss_liters` both start at 0, and `occupancy_end_at` is computed as `pitched_at` plus the recipe's `planned_f1_days` and this batch's `planned_f2_days`, added as whole days. The vessel is occupied and the culture's pitch self-loop fires, so both the vessel's `version` and the culture's `version` increase by 1 alongside the culture's `pitch_count`.

Ingredient consumption is recorded against the batch by naming an `ingredient_lot_id` and a `quantity_used`. The freshness rule is stated deliberately strictly: the lot's `expiry_date` must be **strictly after** the logical clock plus 7 whole days. A lot expiring exactly on that boundary is refused, and so is one already in `status` `EXPIRED`; both answer `ERR_INGREDIENT_EXPIRED`. `quantity_used` may not exceed the lot's `quantity_available`. Recording a use raises `quantity_consumed` and lowers `quantity_available` accordingly, and moves the lot's status: a draw strictly smaller than the remaining availability moves an `AVAILABLE` lot to `PARTIALLY_CONSUMED`, while a draw exactly equal to the remaining availability moves the lot to `CONSUMED` with `quantity_consumed` equal to `quantity_received` and `quantity_available` at 0. That exhausting draw is accepted from `AVAILABLE` as well as from `PARTIALLY_CONSUMED`. The lot's `version` increases by 1.

A consumption record can be undone. Voiding one — with an optional `reason` — sets `voided` to true and stamps `voided_at` with the logical clock, decreases the lot's `quantity_consumed` and increases its `quantity_available` by exactly the recorded `quantity_used`, and bumps the lot's `version`. The restoration must be exact; the ingredient conservation identity in section 2.11 is what an implementation is measured against. A voided record also severs the trace: after the void, the recall cascade can no longer reach that batch through that ingredient lot.

Expiry is stamped, not inferred. A lot in `AVAILABLE` or `PARTIALLY_CONSUMED` whose `expiry_date` falls strictly before a newly set logical clock moves to `EXPIRED` at the moment the clock is moved, and `EXPIRED` is terminal, as is `CONSUMED`. Quarantine is a separate axis and is covered in section 3.7.

### 3.5. The QA Log and the Two Batch Axes

Every batch carries a chronological log of instrument readings, and the log is append-only — a reading is never edited or deleted, which is why a `QaReading` is the one resource in this system that carries no `updated_at` and no `version`. A reading is recorded by a `ProductionOperator` or a `QaManager` and names its `reading_type` (`F1`, `F2` or `PACKAGING`), the instant `reading_at` it was taken, and four measurements: `ph`, `temperature_c` in Celsius, `brix` in degrees Brix, and `abv_pct`. `reading_at` must be at or after the batch's `pitched_at` and at or before the logical clock. The server stamps `recorded_by_user_id` with the acting `X-User-ID` and derives `day_index` as the number of complete days from `pitched_at` to `reading_at`, so the pitch instant itself sits at day index 0.

**Flag evaluation.** Every reading is scored against the readings already on the batch, regardless of their `reading_type`, ordered by `reading_at` ascending with `created_at` ascending as tie-break and restricted to readings strictly earlier than the one being recorded. Four codes may be appended to `flag_reasons`, and they are evaluated in this order:

- `PH_REGRESSION`, when a prior reading exists and this reading's `ph` is more than 0.05 above the immediately preceding reading's `ph`. A rise of exactly 0.05 is not a regression; strictly more is.
- `PH_HARD_FLOOR`, when `ph` is strictly below 2.50. Exactly 2.50 is not a breach.
- `TEMP_EXCURSION`, when `temperature_c` is strictly below 20.0 or strictly above 30.0. Exactly 20.0 and exactly 30.0 are both inside the band.
- `READING_GAP`, when a prior reading exists and the elapsed time from the preceding reading's `reading_at` to this one exceeds 2 days plus 12 hours. A gap of exactly 60 hours is not a `READING_GAP`; strictly more is.

`flagged` is true when `flag_reasons` is non-empty and false when it is empty. The batch's `temp_excursion_count` tracks how many of its readings fell outside the inclusive 20.0-to-30.0 band, and `flagged_reading_count` tracks how many of its readings carry `flagged` true.

**The pH-target stamp is independent of the flag.** A reading may be flagged for a temperature excursion or a missed interval and still be the reading that first reaches the pH target. When the batch's `ph_target_hit_day_index` is still null, this reading's `ph` is at or below the effective ceiling — the lower of the recipe's `target_ph_ceiling` and 3.50 — and this reading's `day_index` is at or above 5 and at or below 14, then `ph_target_hit_day_index` is set to that `day_index`. Both window ends are inclusive, and the stamp is written once and never moved.

**The quality axis.** `qa_disposition` starts at `PENDING` and moves on its own, driven entirely by readings and by one human action. A reading that is not flagged, arriving on a batch whose `flagged_reading_count` is 0, whose `ph` is at or below the effective ceiling and whose `day_index` is at or above 5 and at or below 14, moves the axis `PENDING → CONFORMING` and stamps `ph_target_hit_day_index`. A flagged reading with no hard-fail reason present moves the axis to `AT_RISK` — from `PENDING` and equally from `CONFORMING` — increments `flagged_reading_count` by 1, and records the recording operator's `X-User-ID` in `last_flagged_reading_by_user_id`. A reading that trips a hard fail drives the axis straight to `NONCONFORMING` from `PENDING`, from `CONFORMING` or from `AT_RISK`, and increments `flagged_reading_count`. There are exactly three hard-fail conditions: a `ph` strictly below 2.50; a `day_index` strictly greater than 14 while `ph_target_hit_day_index` is still null; or a temperature excursion that would take `temp_excursion_count` past 2, meaning the third excursion on one batch. `NONCONFORMING` is terminal on the quality axis — such a batch can no longer advance, be drawn from, or be signed off.

**The one way back.** A `QaManager` may apply a corrective sign-off, with an optional `note`, to a batch whose `qa_disposition` is exactly `AT_RISK`, whose `qa_signoff_count` is 0, and whose most recent QA reading has `flagged` false. The signer's `X-User-ID` must differ from `last_flagged_reading_by_user_id`; if it does not, or if the sign-off has already been spent, the answer is `ERR_SEGREGATION_OF_DUTIES`. On success the axis moves `AT_RISK → CONFORMING` and `qa_signoff_count` becomes 1. `flagged_reading_count` is deliberately **not** decremented. A later clean reading, on its own, never restores `CONFORMING` — the human sign-off is the only edge out of `AT_RISK` that does not lead to `NONCONFORMING`, and it may be used at most once per batch.

The quality axis can also be moved from outside the QA log entirely: a cascade arriving from an ingredient-lot quarantine or from a failed culture reverification sets `qa_disposition` to `NONCONFORMING` on any batch whose `ferment_stage` is `F1_ACTIVE`, `F2_ACTIVE` or `READY_TO_PACKAGE`, from `PENDING`, `CONFORMING` or `AT_RISK` alike. Batches already `PACKAGED` or `DUMPED` are skipped.

**The process axis.** `ferment_stage` runs `F1_ACTIVE → F2_ACTIVE → READY_TO_PACKAGE → PACKAGED`, with `DUMPED` reachable as a write-off. Advancing to secondary requires `ferment_stage` `F1_ACTIVE`, a `qa_disposition` other than `NONCONFORMING`, at least one reading of `reading_type` `F1` on the batch, and a non-null `ph_target_hit_day_index` — that is, the effective ceiling must actually have been reached inside the day-5-to-day-14 window, and a batch that never got there is refused with `ERR_PH_WINDOW_MISSED`. The advance stamps `f1_completed_at` and `f2_started_at` with the logical clock and captures `f1_measured_abv_pct` from the latest `F1` reading, ordered by `reading_at` ascending with `created_at` ascending as tie-break.

The projected alcohol figure is computed at that same moment. Take `f1_measured_abv_pct`, add 0.06 percentage points for each day of `planned_f2_days`, add a further 0.0125 percentage points for each gram per liter of `f2_added_sugar_g_per_l`, and round the sum half up to 2 decimal places; the result is `projected_abv_pct`. Classify it against the half-percent line and store the outcome in `projected_abv_class` as `ALCOHOLIC` when the rounded figure is at or above 0.50 and `NON_ALCOHOLIC` when it is strictly below. Worked through as the scaffold states it: an `f1_measured_abv_pct` of 0.20 with 4 planned secondary days and 8 g/L of priming sugar gives 0.20 plus 0.24 plus 0.10, which is 0.54 — `ALCOHOLIC`; with 3 planned days and 4 g/L it gives 0.18 plus 0.18 plus 0.05, which is 0.41 — `NON_ALCOHOLIC`.

Closing secondary fermentation requires `ferment_stage` `F2_ACTIVE`, a `qa_disposition` other than `NONCONFORMING`, and a logical clock at or before `f2_started_at` plus 7 whole days; running past that limit is `ERR_PH_WINDOW_MISSED`, the same code the pH window uses. The close stamps `f2_completed_at`, moves the batch to `READY_TO_PACKAGE`, and frees the vessel back to `DIRTY` with its occupancy interval retained.

A batch may be dumped from `F1_ACTIVE`, from `F2_ACTIVE` or from `READY_TO_PACKAGE`, with an optional `reason`. The dump adds the current `remaining_liters` to `loss_liters` and sets `remaining_liters` to 0, so the batch volume identity still balances, and it frees the vessel when the vessel still points at this batch. `DUMPED` is terminal. `PACKAGED` is reached only by the system, when a packaging run completes and consumes the last of a source batch's liters: a batch whose `remaining_liters` becomes exactly 0 after the run's draws moves `READY_TO_PACKAGE → PACKAGED`, while a batch with liters still left stays `READY_TO_PACKAGE` and can feed a second run.

Finally, the measured alcohol figure. `packaging_abv_pct` is taken from the batch's QA reading whose `reading_type` is `PACKAGING`, choosing the latest by `reading_at` ascending with `created_at` ascending as tie-break. It reads an actual instrument value at fill time, it is computed by no formula at all, and it may land on the other side of the half-percent line from the projection. That disagreement is expected, and section 3.6 says what the plant does about it.

### 3.6. Packaging Runs, Blending and the Emission of a Lot

A packaging run is opened by a `ProductionOperator` against a `run_code`, a `recipe_id`, a `label_approval_id` naming the artwork the run intends to print, a `format` of `KEG`, `BOTTLE` or `CAN`, a `pasteurized` flag, and `max_units_requested`, an upper bound on how many containers to fill. The label revision must belong to the same recipe as the run, and the run's `pasteurized` must be true whenever the recipe's `pasteurization_required` is true. The run opens in `status` `DRAFT` with `created_by_user_id` set to the acting `X-User-ID`, an empty `source_draws` list, `source_batch_count` 0, `gross_liters` 0 and `units_produced` 0. Runs can be filtered afterwards by `recipe_id`, by `label_approval_id`, by `status`, and — for a reverse trace — by `source_batch_id`, which finds every run that drew on a given batch.

**Drawing liquid.** Each draw names a `batch_id`, the `liters_drawn`, and the concurrency token `expected_batch_version`. The batch must be `READY_TO_PACKAGE`, must not be `NONCONFORMING`, and must belong to the same recipe as the run. A run may hold at most 4 draws — `source_batch_count` must be strictly below 4 before a new one is appended — and each individual draw must be at or above 20.0 liters; violating either is `ERR_BLEND_RULE_VIOLATION`. The draw may not exceed the batch's `remaining_liters`, and exceeding it is `ERR_INSUFFICIENT_BATCH_VOLUME`. Each accepted draw appends an entry recording `batch_id`, `liters_drawn` and `drawn_at` to `source_draws` in call order, increments `source_batch_count`, recomputes `gross_liters` as the sum of `liters_drawn` across the list rounded half up to 2 decimals, moves the batch's `drawn_liters` up and its `remaining_liters` down by the same amount, and increments both the batch's `version` and the run's `version`. The first draw moves the run `DRAFT → SOURCED`; every subsequent draw is a self-loop on `SOURCED`.

**The fan-in join.** Starting a run is where the blend is judged as a whole. The state gate deliberately admits a `DRAFT` run so that the zero-draw case is reachable, and a run with no draws then fails on the very next rung with `ERR_BLEND_RULE_VIOLATION`. Beyond that, **every** batch named in `source_draws` must be in `ferment_stage` `READY_TO_PACKAGE` and — this is the join proper — must have `qa_disposition` exactly `CONFORMING`. A single `PENDING` or `AT_RISK` source is enough to hold the whole run, which is why a batch that was drawable at draw time can still be un-startable later. Then the label is tested three ways: its `status` must be `APPROVED`, where a `STALE` revision answers `ERR_LABEL_STALE` and a `DRAFT` or `SUBMITTED` one answers `ERR_INVALID_STATE`; its `approved_recipe_version_number` must still equal the recipe's current `recipe_version_number`, and a mismatch is `ERR_LABEL_STALE`; and its `pasteurized` must equal the run's `pasteurized`, with a mismatch answering `ERR_LABEL_CLASS_MISMATCH`. On success the run moves `SOURCED → IN_PROGRESS` and `started_by_user_id` is stamped.

**Yield.** The start is also when the run's output volume and unit count are fixed. Take `gross_liters`, the rounded sum of the draws. Deduct the 3 % packaging loss allowance — multiply `gross_liters` by 97 and divide by 100 — and round that result half up to 2 decimal places to obtain `net_liters`. Select the container size by format: 19.5 liters for `KEG`, 0.375 liters for `BOTTLE`, 0.355 liters for `CAN`. Divide `net_liters` by that container size and discard the fractional part to get the capacity in whole units, then take `units_produced` as the smaller of that capacity and `max_units_requested`. **The intermediate rounding is load-bearing**: `net_liters` is rounded to 2 decimals *before* the division, and rounding after the division, or skipping the intermediate rounding entirely, changes `units_produced` at the margin. The scaffold's worked example: two draws of 60.00 L and 40.00 L in `BOTTLE` format with `max_units_requested` 300 give `gross_liters` 100.00, `net_liters` 97.00, a capacity of 258 whole bottles, and therefore `units_produced` 258.

**Completion and the divergence test.** Closing the fill requires the run to be `IN_PROGRESS` and requires **every** source batch to carry a `PACKAGING` reading, so that each one's `packaging_abv_pct` is populated; a missing packaging reading is `ERR_VALIDATION`. Then two compliance rungs fire in a fixed order. First, the divergence test: the lot's measured ABV may exceed the greatest `projected_abv_pct` across the source batches by at most 0.05 percentage points, inclusive — a divergence of exactly 0.05 is accepted, strictly more is `ERR_ABV_CLASS_DIVERGENCE`. Second, the class test: the lot's measured `abv_class` must equal the label revision's `abv_class`, and a mismatch is `ERR_LABEL_CLASS_MISMATCH`. When a single request would trip both, the divergence answers first — a measured figure that has run away from its projection is a measurement-integrity problem, and the label mismatch it produces is merely the symptom.

**What the blend inherits.** On a successful completion the run moves `IN_PROGRESS → COMPLETED`, a `FinishedLot` is emitted in `status` `HELD`, and the run's `finished_lot_id` mirrors it. The lot's own `packaging_run_id` and `recipe_id` are the canonical links back. The source batches are read in `drawn_at` ascending order with `created_at` ascending as tie-break, and the lot takes the **worst case** on every inherited attribute:

- `measured_abv_pct` is the greatest `packaging_abv_pct` across the sources, rounded half up to 2 decimals. When two sources share the maximum the value is the same either way, so no tie-break is needed.
- `abv_class` is `ALCOHOLIC` when that figure is at or above 0.50 and `NON_ALCOHOLIC` when it is strictly below.
- `format` and `pasteurized` are copied from the run, `container_liters` is the container size the format selects, and `units_produced` is the run's `units_produced`.
- `cold_chain_max_c` is 21.0 degrees Celsius when the run was pasteurized and 4.0 degrees Celsius when it was not — raw product needs the cold chain, pasteurized product does not.
- `packaged_at` is the logical clock at completion, and `lot_code` is assembled as the first three letters of the recipe's `style` in upper case, then a hyphen, then `packaged_at` rendered as an eight-digit year-month-day, then a hyphen, then the run's `run_code`.

**Shelf life is where the blend really bites.** The shelf window is 270 days for a pasteurized run and 90 days for a raw one. The date it counts from depends on how many batches went in. When `source_batch_count` is exactly 1, the base date is the UTC calendar date of `packaged_at`, so a batch that sat in a brite tank still gets its full window. When `source_batch_count` is 2 or more, the base date is the **earliest** UTC calendar date among the `f2_completed_at` values of the run's source batches, so a blend inherits the oldest liquid's remaining life and expires sooner than either single-source variant would. `best_by_date` is that base date advanced by the shelf window in whole days and normalised to `00:00:00.000Z`. The scaffold's worked example: a raw blend of two batches whose secondary fermentations closed on 2026-05-20 and 2026-05-24, packaged on 2026-05-26, takes 2026-05-20 as its base and yields `2026-08-18T00:00:00.000Z`; the same fill as a single-source raw run packaged on 2026-05-26 yields `2026-08-24T00:00:00.000Z`.

The freshly emitted lot starts with `on_hand_units` equal to `units_produced` and `reserved_units`, `shipped_units`, `poured_units` and `destroyed_units` all at 0. `units_produced` on the lot never changes afterwards; the four buckets move around underneath it, and their sum must always equal it. Each source batch whose `remaining_liters` has fallen to exactly 0 moves to `ferment_stage` `PACKAGED`.

**Abandoning a run.** An abort is accepted from `DRAFT`, from `SOURCED` and from `IN_PROGRESS`, takes an optional `reason`, and moves the run to `ABORTED`. It is a true compensation: for every entry in `source_draws`, the batch's `drawn_liters` is decreased and its `remaining_liters` increased by exactly that entry's liters, and each affected batch's `version` is incremented. `source_draws` itself is retained for audit, and no `FinishedLot` is created. A batch that was drawn and then returned by an abort is not a source of any lot, and an `ABORTED` run is never touched by the recall cascade — it emitted nothing to recall. `COMPLETED` and `ABORTED` are the run's two terminal outcomes, except for the one cascade-only detour: a `COMPLETED` run reached by the ingredient recall cascade moves `COMPLETED → RECALL_FLAGGED`.

### 3.7. Custody of Finished Goods: Hold, Release, Quarantine, Recall

A lot leaves the fill line in `status` `HELD` and it is not saleable yet. Two things must happen before it can be released. The clock must have reached `packaged_at` plus 48 hours — the exact 48-hour instant is already releasable, and anything strictly earlier is `ERR_LOT_HOLD_PERIOD` — and the `QaManager` performing the release must not be the same person, by `X-User-ID`, who opened the packaging run that produced the lot. That second test answers `ERR_SEGREGATION_OF_DUTIES`, and because it depends on stored state it is evaluated *after* the hold-window test, not with the role check: a release that is both too early and self-approved answers `ERR_LOT_HOLD_PERIOD`. A successful release moves `HELD → RELEASED` and stamps `released_by_user_id` and `released_at`.

Only a `RELEASED` lot can back anything. Keg fills, shipment lines and subscription allocations all require it, and a lot in any other status answers `ERR_INVALID_STATE`.

**Quarantine** is available to a `ComplianceOfficer` or a `QaManager` and is accepted from `HELD` as well as from `RELEASED`; it takes an optional `reason`. The status held immediately before is recorded in `pre_quarantine_status`, whose only non-null members are `HELD` and `RELEASED`. Quarantining then runs hops 5, 6 and 7 of the recall cascade from section 2.12: draft and confirmed shipment lines are pulled to `RECALLED` and their reservations released, allocations still `ALLOCATED` are reversed with `reversal_reason` `LOT_QUARANTINED` and credited back, filled kegs from the lot are emptied and counted as destroyed, a `PENDING` notice is raised for every exposed account that does not already hold one for this lot, and each such account's `open_recall_notice_count` is recomputed. A lot already `QUARANTINED`, `RECALLED` or `DEPLETED` is refused with `ERR_INVALID_STATE`.

**Clearance** is the way back, and it is capped. A lot may be cleared out of quarantine **at most once**: `quarantine_clearance_count` must be strictly below 1, and a second attempt answers `ERR_QUARANTINE_CLEARANCE_CAP` — after that the only remaining exit is a recall. A clearance restores `status` to whatever `pre_quarantine_status` holds, increments `quarantine_clearance_count`, and runs the three-hop re-allocation cascade: allocations reversed specifically for `LOT_QUARANTINED` whose `reallocation_attempt_count` is strictly below 2 return to `ALLOCATED` with that counter incremented and the lot's `reserved_units` raised again, and each re-instated allocation takes its `charge_amount` back out of the subscription's `credit_balance`. Allocations reversed for `LOT_RECALLED` or `SUBSCRIPTION_CANCELLED` are never re-instated, an allocation that has already spent both of its two attempts stays `REVERSED`, and shipment lines already set to `RECALLED` are never restored.

**Recall** is available only from `QUARANTINED` and is terminal. It takes an optional `reason`, moves the lot to `RECALLED`, adds the whole of `on_hand_units` to `destroyed_units` and then sets both `on_hand_units` and `reserved_units` to 0, reverses every allocation still `ALLOCATED` with `reversal_reason` `LOT_RECALLED`, and raises a notice with `trigger_source` `LOT_RECALL` for every exposed account that is not already holding a `PENDING` notice for that lot.

The last status, `DEPLETED`, is reached by the system rather than by a caller: after any transition that decreases a lot's `on_hand_units`, a lot in `status` `RELEASED` whose `on_hand_units` has become exactly 0 moves to `DEPLETED`. `RECALLED` and `DEPLETED` are the lot's two terminal statuses.

Raw ingredient lots have their own, simpler quarantine axis. A `ComplianceOfficer` may quarantine a lot in `AVAILABLE`, `PARTIALLY_CONSUMED` or `CONSUMED` — recording `pre_quarantine_status`, whose non-null members here are `AVAILABLE`, `PARTIALLY_CONSUMED` and `CONSUMED` — and this is the root of the full seven-hop cascade. A lot already `EXPIRED` or `QUARANTINED` is refused with `ERR_INVALID_STATE`. Clearing it restores `pre_quarantine_status`, sets `pre_quarantine_status` back to null and increments `quarantine_cleared_count`; unlike the finished-lot clearance, the ingredient clearance has no cap, and it restores nothing downstream — the batches, runs and lots the original cascade touched must each be cleared on their own endpoints.

### 3.8. Keg Assets, the Deposit Ledger and the Taproom

A keg is a returnable asset with a money ledger attached, and its life is a loop rather than a line. It is registered with an `asset_code` and a `capacity_liters` and enters in `status` `IN_STOCK` with `deposit_state` `NONE`, `deposit_amount` 0 and `remaining_liters` 0.

**Filling.** A keg is filled from a released lot by naming the `finished_lot_id` and the `fill_liters` to charge. The fill is accepted from `IN_STOCK`, from `EMPTY` and from `RETURNED` — those last two edges are what close the asset cycle. The lot must be `RELEASED` and its `format` must be `KEG`; the difference between its `on_hand_units` and its `reserved_units` must be at least 1; and `fill_liters` must be strictly positive and at or below the keg's `capacity_liters`. The standard charge for a keg-format container is 19.5 liters, which is the same figure the packaging yield uses to count keg units. On success the keg moves to `FILLED`, `finished_lot_id` and `fill_liters` are stored, the lot's `on_hand_units` drops by 1 while its `poured_units` rises by 1, and `deposit_state` is reset to `NONE` with `deposit_amount` reset to 0 for the new cycle. Both the lot's `version` and the keg's `version` increment. A `SCRAPPED` keg can never be filled again.

**The taproom leg.** `TaproomStaff` puts a filled keg on tap. A keg out on deposit cannot be tapped in house, so `deposit_state` must be `NONE`. If the keg has been on tap before, `last_untapped_at` will be set, and the re-tap is only allowed once the logical clock is **strictly after** that instant plus 15 minutes; a re-tap exactly on the buffer boundary is refused with `ERR_KEG_RETAP_BUFFER`. Tapping stamps `tapped_at` and sets `remaining_liters` to `fill_liters` less the 0.5-liter blow-off allowance, rounded half up to 2 decimals — the allowance is deducted exactly once, at tap time, and never again. A 19.50-liter fill therefore comes on tap showing 19.00 liters. Untapping returns the keg `ON_TAP → FILLED`, stamps `last_untapped_at` with the logical clock and clears `tapped_at` to null.

**Pouring.** A fill is opened against a keg that is `ON_TAP` by naming the `keg_id`, a `container_type` of `HOUSE_GROWLER`, `CUSTOMER_GROWLER` or `GLASS_POUR`, and the `requested_liters`. An optional `customer_birth_date` may be supplied at this point and is required later when the liquid is alcoholic. `requested_liters` must be at or above 0.1 liters, and for either growler type at or below 1.9 liters; a glass pour is not subject to the growler ceiling, and a request outside those bounds is refused with `ERR_VALIDATION`. The fill opens in `fill_status` `REQUESTED` with `charge_amount` 0 until it is poured.

The two container paths diverge here. A `HOUSE_GROWLER` or `GLASS_POUR` fill pours straight from `REQUESTED`. A `CUSTOMER_GROWLER` may not: it must first pass a sanitation inspection, which moves it `REQUESTED → INSPECTED` and stamps `inspected_at` and `inspected_by_user_id`, and it may only be poured from `INSPECTED` while the logical clock is at or before `inspected_at` plus 24 hours. Pouring a customer-owned growler that is still `REQUESTED`, or whose inspection has gone stale, answers `ERR_GROWLER_INSPECTION_REQUIRED`. Inspection is only meaningful for a customer-owned container; it is not offered for the other two types.

The pour itself is judged by the eight-rung ladder in section 2.8: container gate before person gate, person gate before volume. When the keg's lot carries `abv_class` `ALCOHOLIC`, `customer_birth_date` must be present and the customer must be at least 21 years old measured at the logical clock, and a failure is `ERR_AGE_VERIFICATION_REQUIRED`; when the age gate applies and passes, `age_verified` is set to true on the fill. `requested_liters` may not exceed the keg's `remaining_liters` — a pour of exactly the remainder is accepted, and one cent of a liter more is `ERR_INSUFFICIENT_KEG_VOLUME`. On success `fill_status` becomes `POURED`, `poured_liters` is set equal to `requested_liters`, `poured_at` is stamped, and the keg's `remaining_liters` is reduced by the poured amount and re-rounded half up to 2 decimals. A remainder of exactly 0.20 liters keeps the keg `ON_TAP`; a remainder **strictly below** 0.20 liters empties it, moving the keg `ON_TAP → EMPTY` with `remaining_liters` set to 0, `finished_lot_id` cleared to null and `last_untapped_at` stamped with the logical clock. `POURED` is terminal for a fill.

**What the customer pays.** Multiply `requested_liters` by the taproom rate of 9.00 dollars per liter and round half up to 2 decimals; that is the gross. A fill of at or above 1.0 liter earns the 10 % bulk discount — exactly 1.0 liter qualifies — and the discount is the gross multiplied by 10 and divided by 100, rounded half up to 2 decimals; below the tier the discount is zero. Then add the container charges: 3.50 dollars for a `HOUSE_GROWLER` and nothing otherwise, and 1.50 dollars as a sanitation fee for a `CUSTOMER_GROWLER` and nothing otherwise. `charge_amount` is the gross, less the discount, plus whichever of those two fees applies, rounded half up to 2 decimals. A house growler therefore never carries a sanitation fee — the vessel never leaves the building unsanitised — a customer growler carries the sanitation fee instead of the container fee, and a glass pour carries neither, so the same liters always cost strictly less in a glass than in either growler. The scaffold's worked example: 1.20 liters gives a gross of 10.80 and a discount of 1.08, so a `CUSTOMER_GROWLER` costs 11.22, a `HOUSE_GROWLER` costs 13.22, and a `GLASS_POUR` costs 9.72; a 0.50-liter `GLASS_POUR` costs 4.50 with no discount at all. That same 1.20-liter growler fill from a keg showing 19.00 liters leaves 17.80 liters behind.

**The deposit leg.** Instead of going on tap, a filled keg may be issued out to a trade account by a `SalesRep` naming the `account_id`. The keg must be `FILLED` with `deposit_state` `NONE`, the account's `status` must be `ACTIVE`, and when the keg's lot carries `abv_class` `ALCOHOLIC` the account's `alcoholic_license_on_file` must be true — otherwise `ERR_ALCOHOLIC_CHANNEL_RESTRICTED`. Issuing moves the keg `FILLED → ON_DEPOSIT`, records `account_id` and `issued_at`, sets `deposit_state` to `CHARGED` and `deposit_amount` to 45.00 dollars, raises the account's `keg_deposit_balance` by 45.00 and increments its `kegs_charged_lifetime` by 1.

**Settlement.** A return is recorded against a keg that is `ON_DEPOSIT` with `deposit_state` `CHARGED`, and the caller supplies `condition` as either `GOOD` or `DAMAGED`. `returned_at` is stamped with the logical clock, and the number of whole days out is the count of complete days from `issued_at` to `returned_at`. Three outcomes, and only three:

- **On time and undamaged.** `condition` is `GOOD` and the days out are at or below 90. `deposit_forfeit_amount` is 0.00 and `deposit_refund_amount` is 45.00. `deposit_state` becomes `REFUNDED` and the keg moves `ON_DEPOSIT → RETURNED`, back into the fillable pool.
- **Late and undamaged.** `condition` is `GOOD` and the days out are at or above 91 — a return on day 90 exactly is still on time. Forty per cent of the deposit is forfeited, so `deposit_forfeit_amount` is 18.00 and `deposit_refund_amount` is 27.00, each rounded half up to 2 decimals. `deposit_state` becomes `FORFEITED` and the keg still moves to `RETURNED` and is still fillable.
- **Damaged, at any age.** `condition` is `DAMAGED`, and how long the keg was out is irrelevant. One hundred per cent of the deposit is forfeited: `deposit_forfeit_amount` is 45.00 and `deposit_refund_amount` is 0.00. `deposit_state` becomes `FORFEITED` and the keg moves `ON_DEPOSIT → SCRAPPED`, which is terminal — the asset can never be filled again.

In every case the account's `keg_deposit_balance` falls by 45.00, its `deposit_refunded_total` rises by the refund and its `deposit_forfeited_total` rises by the forfeit, the keg's `account_id` is cleared and `deposit_amount` is reset to 0, and both the keg's and the account's `version` increment. The two identities in section 2.11 are the check: the running balance must equal 45.00 times the number of kegs still `CHARGED` against the account, and 45.00 times `kegs_charged_lifetime` must equal the balance plus the lifetime refunds plus the lifetime forfeits. A settlement that pays the refund but forgets to book the forfeit passes the first identity and fails the second.

### 3.9. Trade Accounts, Shipments and the Invoice Ledger

A `SalesRep` opens a trade account with an `account_name`, a `channel` of either `WHOLESALE_DISTRIBUTOR` or `SELF_DISTRIBUTION`, and a `credit_limit` capping how much the account may owe. Two inputs are optional: `credit_terms_days`, the net payment terms in whole days, which defaults to 30, and `alcoholic_license_on_file`, which defaults to false and decides whether the account may receive alcoholic product at all. The account opens in `status` `ONBOARDING` with `outstanding_balance`, `keg_deposit_balance`, `deposit_refunded_total`, `deposit_forfeited_total`, `kegs_charged_lifetime`, `ytd_self_dist_liters` and `open_recall_notice_count` all at 0.

An account must be activated before it can trade: activation is accepted only from `ONBOARDING` and moves the account to `ACTIVE`. A `SalesRep` may also place an account on `CREDIT_HOLD`, with an optional `reason`. Both `ONBOARDING` and `CREDIT_HOLD` fail the shipment-confirmation state gate, and both answer `ERR_INVALID_STATE` there — the distinction between an account that has not started and one that has been stopped is not surfaced in the error code.

**Building a shipment.** A shipment is opened against an `account_id` in `status` `DRAFT` with `created_by_user_id` set to the acting `X-User-ID` and `aging_bucket` `CURRENT`. Lines are added to a `DRAFT` shipment by naming a `finished_lot_id`, the `units` wanted, the `unit_price` in dollars, and the concurrency token `expected_finished_lot_version`. The lot must be `RELEASED`, `units` and `unit_price` must both be strictly positive, and the lot must have enough uncommitted stock: `on_hand_units` less `reserved_units` must be at or above `units`, otherwise `ERR_INSUFFICIENT_LOT_UNITS`. Each accepted line is created with `line_status` `ACTIVE`, its `extended_price` computed as `units` multiplied by `unit_price` rounded half up to 2 decimals and its `line_liters` as `units` multiplied by the lot's `container_liters` rounded the same way, and it immediately raises the lot's `reserved_units` by `units`. **Reservation happens at line-add time, not at confirmation.**

The three shipment totals are always taken over `ACTIVE` lines only; `RECALLED` and `CANCELLED` lines contribute nothing to any of them. `total_units` is the plain sum of `units`, `total_liters` is the sum of the already-rounded `line_liters` values, and `subtotal` is the sum of the already-rounded `extended_price` values, itself rounded half up to 2 decimals. Each line is rounded first and the rounded line values are then summed — never the other way round. These totals are recomputed on every line add and on any transition that changes a line's `line_status`.

**Confirmation** is the commercial gate, and it re-checks everything rather than trusting what was true at line-add time. The nine rungs are pinned in section 2.8; in business terms, the shipment must still be `DRAFT` with at least one `ACTIVE` line, the account must be `ACTIVE`, then compliance is settled, then the statutory ceiling, and only then the money. Every `ACTIVE` line whose lot carries `abv_class` `ALCOHOLIC` requires `alcoholic_license_on_file` to be true, or `ERR_ALCOHOLIC_CHANNEL_RESTRICTED`. For a `SELF_DISTRIBUTION` account, `ytd_self_dist_liters` plus this shipment's `total_liters` must be at or below the annual ceiling of 4000.0 liters — a projected total of exactly 4000.0 is accepted, and strictly more is `ERR_SELF_DIST_CEILING_EXCEEDED`. A `WHOLESALE_DISTRIBUTOR` account is not subject to the ceiling. Confirmation stamps `confirmed_at`, recomputes the three totals, and moves the shipment `DRAFT → CONFIRMED`.

**Credit exposure is computed in a pinned order**, because the trap is testing the limit against a stale balance. Step one: for every shipment of the account whose `status` is `DELIVERED`, recompute `days_past_due` against the *current* logical clock. Step two: for every such shipment recompute `late_fee`, rounding per line and then summing. Step three: `outstanding_balance` is the sum of `subtotal` plus `late_fee` across those `DELIVERED` shipments, rounded half up to 2 decimals. Step four: the exposure is `outstanding_balance` plus the subtotal of the shipment now being confirmed, rounded half up to 2 decimals. Step five: the confirmation is refused when that exposure is **strictly greater** than the account's `credit_limit`; an exposure exactly equal to the limit is accepted. The refusal is `ERR_CREDIT_LIMIT_EXCEEDED`, which carries HTTP 402 rather than the 422 most business refusals use. Only `DELIVERED` shipments feed the balance — `DRAFT`, `CONFIRMED`, `PAID`, `CANCELLED` and `RECALL_HOLD` shipments contribute nothing. As the scaffold works it: with a `credit_limit` of 500.00 and one delivered shipment of three `ACTIVE` lines at 43.60 each, giving a subtotal of 130.80, at 10 days past due the late fee is 1.95 and the balance is 132.75; a new shipment with a subtotal of 367.25 makes the exposure exactly 500.00 and is accepted, while 367.26 makes it 500.01 and is refused.

**Delivery** is accepted only from `CONFIRMED`. It stamps `delivered_on_date` with the logical clock and computes `due_date` as that date plus the account's `credit_terms_days` whole days. For each `ACTIVE` line the lot's `reserved_units` and `on_hand_units` both fall by the line's `units` while its `shipped_units` rises by the same amount, which is why cancelling after delivery is no longer possible. The account's `outstanding_balance` rises by `subtotal`, and for a `SELF_DISTRIBUTION` account `ytd_self_dist_liters` rises by `total_liters`. Any lot whose `on_hand_units` reaches exactly 0 as a result moves to `DEPLETED`. The shipment's `version`, each affected lot's `version` and the account's `version` all increment.

The self-distribution ledger is re-derived rather than merely accumulated: `ytd_self_dist_liters` is the sum of `total_liters` over the account's shipments whose `status` is `DELIVERED` or `PAID`, where the account's `channel` is `SELF_DISTRIBUTION` and the shipment's `delivered_on_date` falls in the same UTC calendar year as the logical clock, rounded half up to 2 decimals. Shipments in `DRAFT`, `CONFIRMED`, `CANCELLED` or `RECALL_HOLD` never count, and a payment does not remove liters from the ledger because a `PAID` shipment is still counted. Likewise `outstanding_balance` is authoritatively the re-derivation described in step three above — the sum of `subtotal` plus `late_fee` over the account's currently-`DELIVERED` shipments — and the increase at delivery and the decrease at payment are the two events that move a shipment into and out of that set.

**Ageing and the late fee.** For a `DELIVERED` shipment, `days_past_due` is the number of complete days from `due_date` to the logical clock, floored at 0 — an invoice that is not yet due reads 0, never a negative number. The number of late months is 0 when `days_past_due` is 0, and otherwise `days_past_due` divided by 30 and rounded **up** to a whole number. `late_fee` is then computed line by line: for each `ACTIVE` line, multiply its `extended_price` by 1.5, divide by 100, multiply by the number of late months, and round that half up to 2 decimals; the shipment's `late_fee` is the sum of those per-line amounts. **Round per line, then sum** — summing the extended prices first and rounding the single product afterwards gives a different cent on ordinary inputs and is wrong. The scaffold's counter-example makes the difference visible: three `ACTIVE` lines each with an `extended_price` of 43.60 at 10 days past due, so one late month, give 0.65 per line and a `late_fee` of 1.95, whereas summing first and rounding once gives 1.96.

`aging_bucket` follows from the same day count: `CURRENT` when `days_past_due` is 0; `B1_1_30` when it is at least 1 and at most 30; `B2_31_60` when it is at least 31 and at most 60; and `B3_61_PLUS` when it is 61 or more. Exactly 30 is `B1_1_30`, exactly 31 is `B2_31_60`, exactly 60 is `B2_31_60`, and exactly 61 is `B3_61_PLUS`. These three figures are recomputed when a shipment is delivered, again whenever the logical clock moves, and again whenever a single shipment is read — so a reader always sees live ageing. A shipment in `CANCELLED` or `RECALL_HOLD` carries a `late_fee` of 0.00 and an `aging_bucket` of `CURRENT`.

**Payment.** A payment names a `shipment_id` and an `amount`, and it applies to exactly one shipment, which must be `DELIVERED`. The `amount` must equal that shipment's `subtotal` plus its `late_fee`, both rounded to 2 decimals; anything else is `ERR_VALIDATION`. Payment stamps `paid_at`, moves the shipment `DELIVERED → PAID`, and **freezes** `days_past_due`, `late_fee` and `aging_bucket` at the values they held at payment time — they stop moving when the clock does. The account's `outstanding_balance` falls by the shipment's `subtotal`. One recovery rule is attached here: when the account is in `CREDIT_HOLD` and, after this payment, no remaining `DELIVERED` shipment of the account is more than 45 days past due, the account returns to `ACTIVE` on its own.

**Cancellation** is accepted from `DRAFT`, from `CONFIRMED` and from `RECALL_HOLD`, and takes an optional `reason`. Every line whose `line_status` is `ACTIVE` moves to `CANCELLED` and the lot's `reserved_units` falls by that line's `units`. Because reservation is a claim on units still on hand rather than a bucket of its own, a cancellation must move exactly zero units between `on_hand_units`, `shipped_units`, `poured_units` and `destroyed_units` — the finished-goods identity must come back to precisely where it started. `PAID` and `CANCELLED` are the shipment's terminal statuses.

`RECALL_HOLD` is reached only by cascade, never by a caller. When a lot is quarantined, each `ACTIVE` line referencing it on a `DRAFT` or `CONFIRMED` shipment moves to `line_status` `RECALLED` with the reservation released, and a `CONFIRMED` shipment additionally moves `CONFIRMED → RECALL_HOLD` while its remaining totals are recomputed over the lines that are still `ACTIVE`. A `DRAFT` shipment keeps `status` `DRAFT` even though its exposed lines move. Shipments already `DELIVERED`, `PAID` or `CANCELLED` are left entirely alone — their exposure is communicated by a recall notice instead of by a status change.

### 3.10. Subscriptions, Boxes and the First-Expiring-First-Out Selector

A subscription is created by a `PlatformAdmin` with a `subscriber_email`, a `subscriber_birth_date`, and a `preferred_recipe_id` naming the recipe whose released lots the boxes will draw from. The email address must be unique across subscriptions whose `status` is `ACTIVE` or `PAUSED`; a cancelled subscription does not block re-use of the address. A new subscription is `ACTIVE`, its `cycle_start_date` is the logical clock, its `cycle_index` is 1, `completed_cycles`, `skips_used_this_year` and `credit_balance` are 0, `pause_windows` is empty, both `current_pause_start_date` and `current_pause_end_date` are null, `age_verified` is false, and `next_cycle_charge` is computed immediately. A cycle is 28 days long and the list price for one is 42.00 dollars.

**What a cycle costs, in a pinned order.** Proration comes first and the loyalty discount is always taken on the prorated base, never on the full list price. The cycle window is the half-open interval that begins at `cycle_start_date` and ends 28 days later, excluding the end. The number of paused days is the count of whole calendar days that lie in **both** that cycle window and the closed interval running from `current_pause_start_date` through `current_pause_end_date` inclusive; the active days are 28 less the paused days. Step one: the prorated base is 42.00 multiplied by the active days, divided by 28, rounded half up to 2 decimals. Step two: the discount rate is 10 % when `completed_cycles` is at or above 6 and 0 otherwise — exactly 6 completed cycles already qualifies for the loyalty tier. Step three: the discount is the prorated base multiplied by that rate and divided by 100, rounded half up to 2 decimals. Step four: `next_cycle_charge` is the prorated base less the discount, rounded half up to 2 decimals. `completed_cycles` is itself derived — it is the count of this subscription's allocations whose `status` is `SHIPPED`. Only the open pause window prorates the current cycle; closed windows already recorded in `pause_windows` affected earlier cycles and are not re-applied.

`next_cycle_charge` is recomputed on creation, on a pause, on a resume and on a skip. As the scaffold works it: against the 42.00 base, a pause of 7 days with `completed_cycles` 0 leaves 21 active days, a prorated base of 31.50, no discount, and a charge of 31.50; the same pause with `completed_cycles` 6 leaves the prorated base at 31.50 with a discount of 3.15 and a charge of 28.35.

**Pausing.** A `Subscriber` pauses their own `ACTIVE` subscription by supplying `start_date` and `end_date`. The interval is **closed at both ends**, so a pause from day 3 through day 9 inclusive removes 7 days, not 6. `end_date` must be on or after `start_date`, and the span, counting both ends, must be at or below 60 days. The requested interval may not intersect any interval already recorded in `pause_windows`, and two closed intervals that merely **touch** at an endpoint do count as intersecting. A span that is too long, or one that conflicts, answers `ERR_PAUSE_WINDOW_CONFLICT`. On success the subscription moves `ACTIVE → PAUSED`, `current_pause_start_date` and `current_pause_end_date` are set, and `next_cycle_charge` is recomputed with the proration in play. Resuming moves `PAUSED → ACTIVE`, appends the now-closed interval to `pause_windows` as a `start_date` and `end_date` pair, clears both current pause fields to null, and recomputes `next_cycle_charge`.

**Skipping** is a self-loop on `ACTIVE` and it is capped at 3 per calendar year: `skips_used_this_year` must be strictly below 3, and no allocation for the current `cycle_index` may still be `ALLOCATED`. Either failure is `ERR_SUBSCRIPTION_SKIP_CAP`. A skip increments `skips_used_this_year` by 1, increments `cycle_index` by 1, advances `cycle_start_date` by 28 whole days, and credits the subscriber. The credit is **not** prorated: it is the full 42.00 list price less the loyalty discount computed on that full price — 42.00 multiplied by the discount rate and divided by 100, rounded half up to 2 decimals, subtracted from 42.00 and rounded again — and the result is added to `credit_balance`. A subscriber with 6 completed cycles who skips therefore banks 42.00 less 4.20, which is 37.80. Skipping a cycle and pausing for the same 28 days consequently leave different money on the account, and that difference is deliberate.

**Cancelling** is accepted from `ACTIVE` and from `PAUSED`, takes an optional `reason`, and moves the subscription to `CANCELLED`, which is terminal. Every allocation still in `status` `ALLOCATED` moves to `REVERSED` with `reversal_reason` `SUBSCRIPTION_CANCELLED` and the corresponding lot's `reserved_units` is decreased by that allocation's `units`. Allocations already `SHIPPED` are untouched.

**Allocating a box.** A `PlatformAdmin` allocates by naming the `subscription_id`, the `cycle_index` the box belongs to, and `expected_finished_lot_version`. `finished_lot_id` is optional: when it is supplied that lot is used directly, and when it is omitted the first-expiring-first-out selector picks one. The `cycle_index` must be unique within the subscription across allocations whose `status` is `ALLOCATED` or `SHIPPED`, so a reversed allocation frees its cycle index for a fresh attempt. Every box is exactly 6 units — `units` is never caller-supplied — and `charge_amount` records the subscription's `next_cycle_charge` as it stands at allocation time. On success the allocation is created in `status` `ALLOCATED` with `reversal_reason` null and `reallocation_attempt_count` 0, and the lot's `reserved_units` rises by 6.

The selector's candidate set is built from lots whose `status` is `RELEASED`, whose `recipe_id` equals the subscription's `preferred_recipe_id`, whose `on_hand_units` less `reserved_units` is at or above 6, and whose `best_by_date` is **strictly after** the logical clock plus 14 whole days. Candidates are ranked by `best_by_date` ascending — first expiring, first out — with `created_at` ascending as tie-break, and the first is taken. Lots in `HELD`, `QUARANTINED`, `RECALLED` or `DEPLETED` are never candidates. When the candidate set is empty the request is refused, and which refusal depends on why: if at least one `RELEASED` lot of the recipe exists but every one of them fails **only** the shelf test, the answer is `ERR_SHELF_LIFE_TOO_SHORT`; otherwise the answer is `ERR_INSUFFICIENT_LOT_UNITS`. On the boundaries, a lot whose `best_by_date` is exactly the clock plus 14 days is **not** eligible — the remaining shelf must be strictly more than 14 days — while available units of exactly 6 **are** enough.

The eleven-rung ladder in section 2.8 governs an explicit allocation, and two of its rungs restate rules already met elsewhere: when the lot carries `abv_class` `ALCOHOLIC` the subscriber must be at least 21 years old at the logical clock, measured from `subscriber_birth_date`, otherwise `ERR_AGE_VERIFICATION_REQUIRED`; and `age_verified` on the subscription is set to true once that check has been made.

**Shipping a box** is accepted only from `ALLOCATED`. The allocation moves to `SHIPPED`, the lot's `reserved_units` and `on_hand_units` both fall by the allocation's `units` while its `shipped_units` rises by the same amount, the subscription's `completed_cycles` is recomputed and `next_cycle_charge` recomputed with it, and both the lot's and the subscription's `version` increment. `SHIPPED` and `REVERSED` are the allocation's two terminal outcomes, save for the one re-entry the clearance cascade allows.

That re-entry is capped. An allocation reversed with `reversal_reason` `LOT_QUARANTINED` may be automatically re-instated at most twice: `reallocation_attempt_count` must be strictly below 2 for a clearance to bring it back, and each re-instatement increments the counter. An allocation reversed for `LOT_RECALLED` or for `SUBSCRIPTION_CANCELLED` is never re-instated by any means.

### 3.11. Recall Notices and Acknowledgement

A recall notice is never created by a caller; it is raised by the cascade. It names the `account_id` being notified and the `finished_lot_id` the notice concerns, and it records `trigger_source` describing where the chain began — `INGREDIENT_LOT_QUARANTINE` when it started at a raw ingredient lot quarantine, `LOT_QUARANTINE` when it started at a finished-lot quarantine, and `LOT_RECALL` when it started at a recall. A notice opens in `status` `PENDING` with `issued_at` set to the logical clock and `ack_deadline_at` computed as `issued_at` plus 24 hours.

Exposure is what earns an account a notice. An account is exposed to a lot when it holds a line with `line_status` `ACTIVE` or `RECALLED` on any of its shipments referencing that lot, or when it holds a keg from that lot with `deposit_state` `CHARGED`. One notice is raised per account-and-lot pair, and an account that already holds a `PENDING` notice for the same lot does not receive a second one.

A `SalesRep` acknowledges a notice on the account's behalf, with an optional `note`. Acknowledgement is accepted from `PENDING` and equally from `OVERDUE`; it stamps `acknowledged_at` and `acknowledged_by_user_id`, moves the notice to `ACKNOWLEDGED`, which is terminal, and decreases the account's `open_recall_notice_count` by 1.

A notice that is not acknowledged in time goes `PENDING → OVERDUE` when the logical clock is moved strictly past its `ack_deadline_at`. This does not change `open_recall_notice_count`, because an overdue notice is still an open one — the account's counter is the number of its notices whose `status` is `PENDING` or `OVERDUE`, and moving between those two statuses leaves the count where it was.

### 3.12. Reading the Plant: Traces and Filters

Traceability is only useful if it runs in both directions, so most read surfaces are collection reads hung off the parent they belong to, and every one of them accepts `limit` and `offset` on top of its own filters.

On the production side, the label revisions drawn against a recipe can be narrowed by `status`; the daughters split directly from a mother culture can be narrowed by `state`; and the consumption records drawn from one ingredient lot are listed with voided rows included, narrowed by `voided` when only one kind is wanted. Batches are listed across the whole plant and can be narrowed by `recipe_id`, by `scoby_culture_id`, by `vessel_id`, by `ferment_stage` and by `qa_disposition`, so both axes of the parallel state machine are independently filterable. One batch's QA log is read in `reading_at` ascending order with `created_at` ascending as tie-break and can be narrowed by `reading_type`, and one batch's consumption records can be narrowed by `voided`.

On the packaging side, runs are listed with filters for `recipe_id`, `label_approval_id` and `status`, plus `source_batch_id`, which is the reverse trace: it answers "which runs drew on this batch". Finished lots are listed with filters for `packaging_run_id`, `recipe_id` and `status`, and that listing doubles as the operator's view of the first-expiring-first-out release order. From a single lot, three further traces hang: the shipment lines drawing on it, narrowed by `line_status`; the subscription allocations drawing on it, narrowed by `status`; and the recall notices raised for it, narrowed by `status`.

On the commercial side, keg assets are listed with filters for `finished_lot_id`, `account_id`, `status` and `deposit_state`, and the taproom fills drawn from one keg can be narrowed by `fill_status`. An account's recall notices are narrowed by `status`. Shipments are listed with filters for `account_id` and `status`, and one shipment's lines by `line_status`. Subscriptions are listed with filters for `status` and `preferred_recipe_id`, and one subscription's allocations by `status`.

Reading a single shipment is the one read in this system with a computed consequence: `days_past_due`, `late_fee` and `aging_bucket` are re-derived at read time so the caller always sees live ageing rather than a figure frozen at the last write. Reading a single account likewise re-derives `ytd_self_dist_liters`, and reading a single culture re-derives `vitality_score`.

## 4. Endpoint Definitions

Every endpoint below is mounted at the root of the service; there is no tenant or vendor prefix. Creating a new resource returns HTTP 201; every other successful operation, including every state transition and every read, returns HTTP 200. Success bodies carry the affected resource in `data` under the envelope described in section 2.2. This table is deliberately minimal — it states the method, the path, what the operation is for, and who may call it. The request payload, the response payload and the side effects of each operation are specified in the narratives of sections 2 and 3, and must be reconstructed from there.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server's logical clock. Before any call the clock reads exactly 2026-05-01T00:00:00Z and MUST NOT fall back to wall-clock time. | `PlatformAdmin` |
| POST | `/recipes` | Create a recipe at recipe_version_number 1 | `ProductionOperator`, `PlatformAdmin` |
| POST | `/recipes/{id}/revise` | Bump the recipe revision; every approved label for the recipe goes stale | `ProductionOperator`, `PlatformAdmin` |
| GET | `/recipes/{id}` | Read one recipe | `ProductionOperator`, `QaManager`, `ComplianceOfficer`, `PlatformAdmin` |
| GET | `/recipes/{id}/label-approvals` | Every label revision drawn against this recipe | `ProductionOperator`, `QaManager`, `ComplianceOfficer`, `PlatformAdmin` |
| POST | `/label-approvals` | Open a label revision in DRAFT | `ComplianceOfficer`, `PlatformAdmin` |
| POST | `/label-approvals/{id}/submit` | Submit a DRAFT or STALE revision for approval | `ComplianceOfficer`, `PlatformAdmin` |
| POST | `/label-approvals/{id}/approve` | Approve a SUBMITTED revision; the approver must not be the submitter | `ComplianceOfficer`, `PlatformAdmin` |
| POST | `/scoby-cultures` | Propagate a founder culture, or split a daughter from a mother when parent_culture_id is supplied | `ProductionOperator`, `PlatformAdmin` |
| POST | `/scoby-cultures/{id}/reverify` | Send an ACTIVE culture for laboratory reverification | `QaManager`, `PlatformAdmin` |
| POST | `/scoby-cultures/{id}/reverify-result` | Record the laboratory outcome; PASS returns the culture to service, FAIL contaminates it | `QaManager`, `PlatformAdmin` |
| POST | `/scoby-cultures/{id}/retire` | Retire an ACTIVE culture from service | `ProductionOperator`, `PlatformAdmin` |
| GET | `/scoby-cultures/{id}` | Read one culture, including its derived vitality_score | `ProductionOperator`, `QaManager`, `ComplianceOfficer`, `PlatformAdmin` |
| GET | `/scoby-cultures/{id}/daughters` | Cultures split directly from this mother | `ProductionOperator`, `QaManager`, `ComplianceOfficer`, `PlatformAdmin` |
| POST | `/vessels` | Register a fermentation vessel in state DIRTY | `ProductionOperator`, `PlatformAdmin` |
| POST | `/vessels/{id}/cip-start` | Begin a clean-in-place cycle | `ProductionOperator`, `PlatformAdmin` |
| POST | `/vessels/{id}/cip-complete` | Finish a clean-in-place cycle; sanitation is valid for VESSEL_CIP_VALID_HOURS from this instant | `ProductionOperator`, `PlatformAdmin` |
| GET | `/vessels/{id}` | Read one vessel, including its sanitation and occupancy fields | `ProductionOperator`, `QaManager`, `ComplianceOfficer`, `PlatformAdmin` |
| POST | `/ingredient-lots` | Receive a raw ingredient lot | `ProductionOperator`, `PlatformAdmin` |
| POST | `/ingredient-lots/{id}/quarantine` | Quarantine a raw ingredient lot; this is the root of the seven-hop recall cascade | `ComplianceOfficer`, `PlatformAdmin` |
| POST | `/ingredient-lots/{id}/clear-quarantine` | Release a raw ingredient lot back to its pre-quarantine status | `ComplianceOfficer`, `PlatformAdmin` |
| GET | `/ingredient-lots/{id}` | Read one raw ingredient lot | `ProductionOperator`, `QaManager`, `ComplianceOfficer`, `PlatformAdmin` |
| GET | `/ingredient-lots/{id}/uses` | Every batch use drawn from this ingredient lot, voided rows included | `ProductionOperator`, `QaManager`, `ComplianceOfficer`, `PlatformAdmin` |
| POST | `/batches` | Pitch a batch: occupies a sanitised vessel and consumes one pitch from the culture | `ProductionOperator`, `PlatformAdmin` |
| POST | `/batches/{id}/advance-to-f2` | Close primary fermentation and start secondary; computes the projected ABV | `ProductionOperator`, `PlatformAdmin` |
| POST | `/batches/{id}/complete-f2` | Close secondary fermentation, free the vessel, and make the batch drawable | `ProductionOperator`, `PlatformAdmin` |
| POST | `/batches/{id}/dump` | Write off a batch | `ProductionOperator`, `PlatformAdmin` |
| POST | `/batches/{id}/qa-signoff` | Corrective QA sign-off returning an AT_RISK batch to CONFORMING; the signer must not be the operator who recorded the last flagged reading | `QaManager`, `PlatformAdmin` |
| POST | `/batches/{id}/qa-readings` | Append a pH / temperature / Brix / ABV reading to the batch QA log | `ProductionOperator`, `QaManager`, `PlatformAdmin` |
| POST | `/batches/{id}/ingredient-uses` | Record consumption of a raw ingredient lot by this batch | `ProductionOperator`, `PlatformAdmin` |
| GET | `/batches/{id}` | Read one batch, including both state axes and the projected ABV | `ProductionOperator`, `QaManager`, `ComplianceOfficer`, `PlatformAdmin` |
| GET | `/batches` | List batches with filters | `ProductionOperator`, `QaManager`, `ComplianceOfficer`, `PlatformAdmin` |
| GET | `/batches/{id}/qa-readings` | The batch QA log ordered by reading_at ASC, tie-break created_at ASC | `ProductionOperator`, `QaManager`, `ComplianceOfficer`, `PlatformAdmin` |
| GET | `/batches/{id}/ingredient-uses` | Ingredient consumption records for this batch | `ProductionOperator`, `QaManager`, `ComplianceOfficer`, `PlatformAdmin` |
| POST | `/batch-ingredient-uses/{id}/void` | Void a consumption record and return the quantity to the ingredient lot | `ProductionOperator`, `PlatformAdmin` |
| POST | `/packaging-runs` | Open a packaging run in DRAFT against a recipe and a label revision | `ProductionOperator`, `PlatformAdmin` |
| POST | `/packaging-runs/{id}/sources` | Draw liters from one READY_TO_PACKAGE batch into this run; OCC-guarded on the batch | `ProductionOperator`, `PlatformAdmin` |
| POST | `/packaging-runs/{id}/start` | Fan-in join: begin the fill once every source batch is READY_TO_PACKAGE and CONFORMING and the label is current | `ProductionOperator`, `PlatformAdmin` |
| POST | `/packaging-runs/{id}/complete` | Close the fill and emit the FinishedLot with its inherited blend attributes | `ProductionOperator`, `PlatformAdmin` |
| POST | `/packaging-runs/{id}/abort` | Abandon the run and return every drawn liter to its source batch | `ProductionOperator`, `PlatformAdmin` |
| GET | `/packaging-runs/{id}` | Read one packaging run, including its source draws and yield | `ProductionOperator`, `QaManager`, `ComplianceOfficer`, `PlatformAdmin` |
| GET | `/packaging-runs` | List packaging runs with filters, including a reverse trace by source batch | `ProductionOperator`, `QaManager`, `ComplianceOfficer`, `PlatformAdmin` |
| POST | `/finished-lots/{id}/release` | Release a HELD lot to finished goods after the minimum hold; the releaser must not be the run's creator | `QaManager`, `PlatformAdmin` |
| POST | `/finished-lots/{id}/quarantine` | Quarantine a finished lot and unwind its downstream commitments | `ComplianceOfficer`, `QaManager`, `PlatformAdmin` |
| POST | `/finished-lots/{id}/clear-quarantine` | Clear a lot out of quarantine, at most LOT_QUARANTINE_CLEARANCE_CAP times, re-instating eligible subscription allocations | `ComplianceOfficer`, `PlatformAdmin` |
| POST | `/finished-lots/{id}/recall` | Recall a QUARANTINED lot; on-hand units are destroyed and remaining allocations reversed | `ComplianceOfficer`, `PlatformAdmin` |
| GET | `/finished-lots/{id}` | Read one finished lot, including its four unit buckets and reserved_units | `ProductionOperator`, `QaManager`, `ComplianceOfficer`, `SalesRep`, `TaproomStaff`, `PlatformAdmin` |
| GET | `/finished-lots` | List finished lots with filters; the operator view of the FEFO release order | `ProductionOperator`, `QaManager`, `ComplianceOfficer`, `SalesRep`, `TaproomStaff`, `PlatformAdmin` |
| GET | `/finished-lots/{id}/shipment-lines` | Every shipment line drawing on this lot | `SalesRep`, `ComplianceOfficer`, `QaManager`, `PlatformAdmin` |
| GET | `/finished-lots/{id}/allocations` | Every subscription allocation drawing on this lot | `SalesRep`, `ComplianceOfficer`, `QaManager`, `PlatformAdmin` |
| GET | `/finished-lots/{id}/recall-notices` | Recall notices raised for this lot | `SalesRep`, `ComplianceOfficer`, `QaManager`, `PlatformAdmin` |
| POST | `/kegs` | Register a keg asset in IN_STOCK | `ProductionOperator`, `PlatformAdmin` |
| POST | `/kegs/{id}/fill` | Fill a keg from a RELEASED lot of format KEG | `ProductionOperator`, `PlatformAdmin` |
| POST | `/kegs/{id}/tap` | Put a filled keg on tap; the blow-off allowance is deducted once | `TaproomStaff`, `PlatformAdmin` |
| POST | `/kegs/{id}/untap` | Take a keg off tap; the re-tap buffer starts here | `TaproomStaff`, `PlatformAdmin` |
| POST | `/kegs/{id}/issue` | Send a filled keg out to an account on deposit | `SalesRep`, `PlatformAdmin` |
| POST | `/kegs/{id}/return` | Take a keg back and settle the deposit | `SalesRep`, `PlatformAdmin` |
| GET | `/kegs/{id}` | Read one keg asset | `ProductionOperator`, `TaproomStaff`, `SalesRep`, `ComplianceOfficer`, `PlatformAdmin` |
| GET | `/kegs` | List keg assets with filters | `ProductionOperator`, `TaproomStaff`, `SalesRep`, `ComplianceOfficer`, `PlatformAdmin` |
| GET | `/kegs/{id}/fills` | Taproom fills drawn from this keg | `TaproomStaff`, `PlatformAdmin` |
| POST | `/accounts` | Open a trade account in ONBOARDING | `SalesRep`, `PlatformAdmin` |
| POST | `/accounts/{id}/activate` | Move an ONBOARDING account to ACTIVE | `SalesRep`, `PlatformAdmin` |
| POST | `/accounts/{id}/credit-hold` | Place an ACTIVE account on credit hold | `SalesRep`, `PlatformAdmin` |
| POST | `/accounts/{id}/payments` | Apply a payment to one DELIVERED shipment; clears the credit hold when nothing is badly past due | `SalesRep`, `PlatformAdmin` |
| GET | `/accounts/{id}` | Read one account, including the deposit ledger totals and the self-distribution ledger | `SalesRep`, `ComplianceOfficer`, `PlatformAdmin` |
| GET | `/accounts/{id}/recall-notices` | Recall notices addressed to this account | `SalesRep`, `ComplianceOfficer`, `PlatformAdmin` |
| POST | `/shipments` | Open a shipment in DRAFT for an account | `SalesRep`, `PlatformAdmin` |
| POST | `/shipments/{id}/lines` | Add a line and reserve the units on the lot; OCC-guarded on the lot | `SalesRep`, `PlatformAdmin` |
| POST | `/shipments/{id}/confirm` | Confirm a DRAFT shipment against the compliance, ceiling and credit gates | `SalesRep`, `PlatformAdmin` |
| POST | `/shipments/{id}/deliver` | Record delivery; reservations become shipped units and the invoice clock starts | `SalesRep`, `PlatformAdmin` |
| POST | `/shipments/{id}/cancel` | Cancel a shipment and release every reservation it holds | `SalesRep`, `PlatformAdmin` |
| GET | `/shipments/{id}` | Read one shipment, including live days_past_due, late_fee and aging_bucket | `SalesRep`, `ComplianceOfficer`, `PlatformAdmin` |
| GET | `/shipments` | List shipments with filters | `SalesRep`, `ComplianceOfficer`, `PlatformAdmin` |
| GET | `/shipments/{id}/lines` | Lines on this shipment | `SalesRep`, `ComplianceOfficer`, `PlatformAdmin` |
| POST | `/subscriptions` | Start a subscription in ACTIVE on cycle 1 | `PlatformAdmin` |
| POST | `/subscriptions/{id}/pause` | Open a closed pause window on the subscription | `Subscriber`, `PlatformAdmin` |
| POST | `/subscriptions/{id}/resume` | Close the open pause window and return to ACTIVE | `Subscriber`, `PlatformAdmin` |
| POST | `/subscriptions/{id}/skip` | Skip the current cycle and take the credit | `Subscriber`, `PlatformAdmin` |
| POST | `/subscriptions/{id}/cancel` | Cancel the subscription and reverse every outstanding allocation | `Subscriber`, `PlatformAdmin` |
| GET | `/subscriptions/{id}` | Read one subscription, including next_cycle_charge and credit_balance | `Subscriber`, `SalesRep`, `PlatformAdmin` |
| GET | `/subscriptions` | List subscriptions with filters | `SalesRep`, `PlatformAdmin` |
| GET | `/subscriptions/{id}/allocations` | Allocations on this subscription | `Subscriber`, `SalesRep`, `PlatformAdmin` |
| POST | `/subscription-allocations` | Allocate a box for a cycle; when finished_lot_id is omitted the FEFO selector in calculations.finished_goods_release_order picks the lot. OCC-guarded on the lot. | `PlatformAdmin` |
| POST | `/subscription-allocations/{id}/ship` | Ship an allocated box | `PlatformAdmin` |
| POST | `/taproom-fills` | Open a taproom pour or growler fill against a keg that is ON_TAP | `TaproomStaff`, `PlatformAdmin` |
| POST | `/taproom-fills/{id}/inspect` | Record a passed sanitation inspection on a customer-owned growler | `TaproomStaff`, `PlatformAdmin` |
| POST | `/taproom-fills/{id}/pour` | Pour the fill, drawing down the keg and charging the customer | `TaproomStaff`, `PlatformAdmin` |
| POST | `/recall-notices/{id}/acknowledge` | Acknowledge a recall notice on behalf of the account | `SalesRep`, `PlatformAdmin` |

## 5. Error Code Catalogue

Every error response carries the envelope in section 2.2 with `response_type` set to `error` and the identifier below in `data.error_id`. The conditions that raise each code are not repeated here — they are stated where the rule they guard is specified, in sections 2 and 3.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_PRODUCTION_RESOURCE_NOT_FOUND` | 404 |
| `ERR_PACKAGING_RESOURCE_NOT_FOUND` | 404 |
| `ERR_COMMERCIAL_RESOURCE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SCOBY_GENERATION_CAP` | 422 |
| `ERR_SCOBY_VITALITY_TOO_LOW` | 422 |
| `ERR_VESSEL_UNAVAILABLE` | 409 |
| `ERR_VESSEL_CIP_EXPIRED` | 422 |
| `ERR_VESSEL_CAPACITY_EXCEEDED` | 422 |
| `ERR_INGREDIENT_EXPIRED` | 422 |
| `ERR_PH_WINDOW_MISSED` | 422 |
| `ERR_LABEL_STALE` | 409 |
| `ERR_LABEL_CLASS_MISMATCH` | 422 |
| `ERR_ABV_CLASS_DIVERGENCE` | 422 |
| `ERR_BLEND_RULE_VIOLATION` | 422 |
| `ERR_INSUFFICIENT_BATCH_VOLUME` | 422 |
| `ERR_LOT_HOLD_PERIOD` | 422 |
| `ERR_QUARANTINE_CLEARANCE_CAP` | 422 |
| `ERR_INSUFFICIENT_LOT_UNITS` | 422 |
| `ERR_SHELF_LIFE_TOO_SHORT` | 422 |
| `ERR_KEG_RETAP_BUFFER` | 422 |
| `ERR_INSUFFICIENT_KEG_VOLUME` | 422 |
| `ERR_GROWLER_INSPECTION_REQUIRED` | 422 |
| `ERR_AGE_VERIFICATION_REQUIRED` | 403 |
| `ERR_ALCOHOLIC_CHANNEL_RESTRICTED` | 422 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_SELF_DIST_CEILING_EXCEEDED` | 422 |
| `ERR_SUBSCRIPTION_SKIP_CAP` | 422 |
| `ERR_PAUSE_WINDOW_CONFLICT` | 409 |
