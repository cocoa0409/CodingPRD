# Appliance Assembly Plant API — Product Requirements Document

## 1. Introduction

A major appliance assembly plant is one of the few manufacturing environments where a single physical line must absorb almost unbounded product variety. Washing machines, dishwashers and refrigerators of different product families, each carrying its own option build code, flow down the same conveyor at a fixed takt; every option a customer ticks adds work content at a station that has only so many square metres of line-side space and only so many operator minutes per shift. This API is the plant's system of record for that balancing act. It owns the mixed-model build sequence, the synchronous call-off of sequenced modules from suppliers, the quality gates each appliance must clear before it can be sold, the engineering changes that quietly rewrite the bill of materials mid-month, and the field-failure feedback loop that justifies those changes in the first place.

Three pressures shape every rule in this document. The first is **finite capacity**: line-side presentation slots and shift labour minutes are consumed by build slots as they are sequenced and must be released, exactly and completely, when a slot is un-sequenced or a finished appliance ships. The second is **compliance**: an appliance may not be shipped until electrical-safety, leak and functional-cycle gates have passed and an energy/water efficiency index has been certified, and a part cut out of production still carries a multi-year service-supply obligation that survives the change that retired it. The third is **traceability**: every warranty teardown must be attributable to the exact bill of materials the returned appliance was built against, not the bill of materials in force today.

The API is deliberately flat. Every entity is its own top-level collection, and relationships travel in request bodies and query filters rather than in nested URL paths. Readers implementing this specification should expect that the interesting behaviour lives in the interaction between collections — a supplier's on-time score silently un-sequencing a build slot, an engineering change cut-in silently cancelling a dock call — rather than in any single endpoint.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts that hold for every endpoint in the API. Where §3 describes what the plant does, this section describes the invariant frame inside which it does it.

### 2.1. Plant Personnel and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user is acting. A request with a missing or empty `X-User-ID` is rejected with `ERR_UNAUTHENTICATED`. A request whose `X-User-Role` is missing, is not one of the role names below, or is not on the authorized-role list of the endpoint being called is rejected with `ERR_ROLE_NOT_PERMITTED`.

Seven roles exist, spelled exactly as follows:

- `PlantAdmin` — owner of master data: lines, stations, model variants, suppliers and parts. A plant administrator may also drive line stop/start and the planner's scheduling operations during setup, but never records quality tests, never decides engineering changes and never analyses warranty returns.
- `ProductionPlanner` — owner of the mixed-model build sequence, dock call-offs and shift staffing.
- `LineOperator` — runs the line: stopping and starting it, performing family changeovers, releasing build slots, completing assembly and shipping finished appliances.
- `QualityInspector` — owner of the quality gates, quarantine release and efficiency certification.
- `EngineeringLead` — authors bill-of-materials lines and drives the engineering-change lifecycle.
- `WarrantyAnalyst` — owner of field-failure analytics: return intake, teardown, disposition, design feedback and withdrawal.
- `SupplierPortal` — an external supplier user.

Throughout this document, **the six plant-internal roles** means `PlantAdmin`, `ProductionPlanner`, `LineOperator`, `QualityInspector`, `EngineeringLead` and `WarrantyAnalyst` — every role except `SupplierPortal`.

For the six plant-internal roles, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it — it is stored as `submitted_by_user_id` when an engineering change is submitted and as `decided_by_user_id` when one is decided, and those two values are compared with each other to enforce segregation of duties — but it is never compared against any entity's `id`. Concretely: when `X-User-Role` is `PlantAdmin`, `ProductionPlanner`, `LineOperator`, `QualityInspector`, `EngineeringLead` or `WarrantyAnalyst`, no ownership check of any kind is derived from `X-User-ID`.

`SupplierPortal` is the one exception. When `X-User-Role` is `SupplierPortal`, `X-User-ID` **is** the `id` of the acting supplier; every read and write available to that role is scoped to it. Ownership checks compare the target row's `supplier_id` foreign key to `X-User-ID`: recording an arrival against a delivery call belonging to another supplier, reading another supplier's record, listing delivery calls that are not the caller's own, or filtering the part catalogue by a `supplier_id` other than the caller's own are all rejected with `ERR_SUPPLIER_SCOPE_VIOLATION`. A `SupplierPortal` caller who supplies no `supplier_id` filter on a list read sees only its own rows.

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

List endpoints accept two query parameters. `limit` caps the number of records returned; when omitted it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100. A `limit` outside that inclusive range is a schema violation and is rejected with `ERR_INVALID_REQUEST`. `offset` is the number of records skipped before the page begins; when omitted it defaults to 0, and it may not be negative.

Unless a specific list endpoint states otherwise, records are returned sorted by `created_at` in ascending order. The endpoints that override that default are: the stations of a line, ordered by `position_index` ascending (which is also the allocation order for line-side presentation); delivery calls, ordered by `window_start` ascending and then `created_at` ascending; the shift plans of a line, ordered by `shift_start` ascending and then `created_at` ascending; build slots, ordered by `sequence_index` ascending; production units, ordered by `built_at_sequence_index` ascending; the quality tests of a unit, ordered by `created_at` ascending; engineering changes, ordered by `created_at` ascending; and warranty returns, ordered by `returned_at` ascending.

Every list response repeats `limit` and `offset` in the `meta` object alongside `total_count` (the number of records matching the filters before pagination) and `has_more` (true when records remain beyond the current page).

### 2.4. The Plant Logical Clock

Every temporal rule in this specification — delivery-window comparisons, lateness arithmetic, the miss grace period, service-supply obligations, shift coverage and the checkpoint sweep — is evaluated against a server-held **logical clock** rather than wall-clock time, so that plant scenarios can be driven deterministically. Before the clock has ever been set it reads `2026-08-01T00:00:00Z`; that default is mandatory. Any of the six plant-internal roles may move the clock by supplying a `current_utc` instant to the clock-setting capability described in §4; the call mutates no entity, and the response echoes the new `current_utc`. Subsequent reads of derived temporal state reflect the new instant immediately.

Whenever this document says "the logical clock", it means the value most recently set, or the mandatory default if it has never been set.

### 2.5. Record Identity, Audit Fields and Versioning

Every resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp rendered as an ISO 8601 UTC instant with three fractional digits (for example `2026-08-01T06:15:00.000Z`).

Almost every resource additionally carries `updated_at`, an ISO 8601 UTC timestamp refreshed whenever the resource's stored state changes, and `version`, an integer that begins at 1 on creation and increments by one on each mutation of that resource. Lines, stations, model variants, suppliers, parts, bill-of-materials lines, delivery calls, shift plans, build slots, production units, engineering changes and warranty returns all behave this way.

The single exception is the quality test. A quality test is an append-only measurement record: it carries `id` and `created_at` only. It has **no** `updated_at` and **no** `version`, and no client-facing endpoint updates one. Its `status` moves from `RECORDED` to `VOIDED` only as a side effect of a quarantine clearance.

Two version counters are read by clients as concurrency tokens, so the operations that advance them must be predictable. A line's `version` advances by exactly one when a station is created on it, when it is stopped, when it is started, and when a shift plan is created for it. A model variant's `version` advances by exactly one when it is released, when it is made obsolete, and when a bill-of-materials line is authored against it. Recomputations of a line's derived fields that follow from sequencing or un-sequencing a build slot, from shipping a unit, or from a checkpoint sweep refresh the line's `updated_at` but do not themselves advance the line's `version`.

### 2.6. Measurement Precision and Rounding Discipline

Every derived number in this system has a pinned precision and a pinned rounding direction. Unless stated otherwise, rounding is **half up**.

- Percentages and scores carried to two decimal places, half up: `free_slot_pct`, `on_time_score`, `cohort_failure_rate_per_1000` and the reported shipped-exposure rate.
- The efficiency ratios: each individual test ratio is rounded to two decimal places half up, each per-type mean to four decimal places half up, and the final `efficiency_index` and `provisional_efficiency_index` to two decimal places half up.
- The option-load staffing factor is rounded to four decimal places before it is multiplied into the cap, and the resulting cap is made an integer by rounding **down** to the next whole number, with that rounding-down applied exactly once, to the product of all factors.
- `committed_labor_minutes` is an integer produced by rounding **up**, applied exactly once, at the very end of the calculation.
- `lateness_minutes` is an integer produced by rounding **up** to the next whole minute.
- The per-station `slot_units` of a presentation allocation is an integer produced by rounding **up**, applied to the whole quotient rather than to any single operand.

Numbers are returned in response bodies as JSON numbers, never as strings. Input fields preserve the precision supplied by the client.

### 2.7. Stale-View Rejection on Master-Data Writes

Two write endpoints can silently retire a record the client has never seen, so both are guarded by optimistic concurrency control. In each case the version field is a **required** input, not an optional one; omitting it is a schema violation rejected with `ERR_INVALID_REQUEST`.

Authoring a bill-of-materials line requires `expected_model_variant_version`, carrying the `version` of the target model variant as the client last observed it. If the variant's current `version` differs — because another writer has authored a line, released the variant, or made it obsolete since the client's last read — the request is rejected with `ERR_STALE_MODEL_VARIANT_VERSION` and HTTP 412. The guard matters because a new line for a given `bom_position_code` legitimately supersedes any active line at the same position, so a writer holding a stale view of the variant's bill of materials would retire a line it never saw.

Creating a shift plan requires `expected_line_version`, carrying the `version` of the target line as the client last observed it. If the line's current `version` differs, the request is rejected with `ERR_STALE_LINE_VERSION` and HTTP 412. The guard matters because a plan for an already-planned combination of `shift_date` and `shift_code` supersedes the prior plan and repoints its build slots, so a stale writer would re-staff a shift whose current plan it never observed.

No other endpoint in this API accepts a version field, and no other endpoint performs a version comparison.

### 2.8. The Validation Ladder

All checks are evaluated in one global ascending priority order, and the **first** violation encountered determines the response. When any rule on the ladder fires, **no** mutation of any kind occurs — not to the target entity, not to any entity that would have been cascaded into. Where an endpoint is subject to several rules, the ladder position, not the order in which this document happens to discuss them, decides which error the client sees.

1. `X-User-ID` is present and non-empty, on every endpoint — otherwise `ERR_UNAUTHENTICATED`.
2. `X-User-Role` is one of the seven roles and appears on the endpoint's authorized-role list, on every endpoint — otherwise `ERR_ROLE_NOT_PERMITTED`.
3. Body and query shape, on every endpoint: required fields present, types correct, enum members recognized, numeric bounds honoured (`takt_seconds` at least 1; `option_load_limit_pct` greater than 0 and at most 100; `qty_per_unit` at least 1; `option_content_points` between 0 and 10 inclusive; `overtime_minutes` between 0 and 120 inclusive; `sequence_index` at least 1; `effective_at_sequence` at least 1; `limit` between 1 and 100 inclusive; `offset` not negative), timestamps well-formed ISO 8601, `window_start` strictly before `window_end`, and `shift_start` strictly before `shift_end`. Otherwise `ERR_INVALID_REQUEST`.
4. The `{id}` path parameter resolves to an entity of the endpoint's own type, on every endpoint carrying one, and the failure carries that entity's own not-found code: `ERR_LINE_NOT_FOUND`, `ERR_STATION_NOT_FOUND`, `ERR_MODEL_VARIANT_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`, `ERR_PART_NOT_FOUND`, `ERR_BOM_LINE_NOT_FOUND`, `ERR_DELIVERY_CALL_NOT_FOUND`, `ERR_SHIFT_PLAN_NOT_FOUND`, `ERR_BUILD_SLOT_NOT_FOUND`, `ERR_PRODUCTION_UNIT_NOT_FOUND`, `ERR_ENGINEERING_CHANGE_NOT_FOUND` or `ERR_WARRANTY_RETURN_NOT_FOUND`.
5. Every foreign key carried in a request body or query string resolves to an existing record, checked in the order the fields are declared in that endpoint's input list, and reported with the referenced entity's own not-found code. This rule guards station creation, part creation, bill-of-materials line authoring, delivery-call creation, shift-plan creation, build-slot creation, engineering-change creation, warranty-return creation, warranty-return analysis, and every filtered list read.
6. A `SupplierPortal` caller may act only on rows whose `supplier_id` equals `X-User-ID` — otherwise `ERR_SUPPLIER_SCOPE_VIOLATION`. This applies to arrival recording, the single-supplier read, the delivery-call list and the part list.
7. The concurrency tokens of §2.7: `expected_model_variant_version` must equal the variant's `version` on bill-of-materials line authoring, and `expected_line_version` must equal the line's `version` on shift-plan creation — otherwise `ERR_STALE_MODEL_VARIANT_VERSION` or `ERR_STALE_LINE_VERSION` respectively, at HTTP 412.
8. The caller deciding an engineering change must not be the change's `submitted_by_user_id` — otherwise `ERR_SEGREGATION_OF_DUTIES`.
9. The target entity is in a state from which the requested transition exists, on every action endpoint, including cross-dimension guards such as shipping requiring a certified quality status — otherwise `ERR_INVALID_STATE`.
10. Test applicability on quality-test recording: a `LEAK` test only when the model variant has `requires_leak_test` true, and a `WATER` test only when the variant's `water_liters_limit` is not null; and, more generally, a test of any type only when the variant's governing limit field for that type is non-null, so an `ELECTRICAL_SAFETY` test against a variant carrying no `hipot_leakage_ma_limit`, or an `ENERGY` test against one carrying no `energy_kwh_limit`, is refused on the same rung — otherwise `ERR_TEST_NOT_APPLICABLE`.
11. Quality gate order on quality-test recording: `ELECTRICAL_SAFETY` comes first, `LEAK` and `FUNCTIONAL_CYCLE` require a `quality_status` of `SAFETY_PASSED` or `GATED`, and `ENERGY` and `WATER` require a `quality_status` of `GATED` — otherwise `ERR_QUALITY_GATE_ORDER`.
12. A quarantined unit accepts no assembly progress and no new measurement: assembly completion, shipping and quality-test recording on a unit whose `quality_status` is `QUARANTINED` are rejected with `ERR_UNIT_QUARANTINED`. On assembly completion and on shipping this quarantine check is evaluated **ahead of** the assembly-dimension state check of rule 9, so a quarantined unit — which is necessarily sitting in `REWORK` — always reports `ERR_UNIT_QUARANTINED` and never `ERR_INVALID_STATE`; on quality-test recording, by contrast, rules 10 and 11 still fire first, so a `LEAK` or `ENERGY` test against a quarantined unit reports `ERR_QUALITY_GATE_ORDER`. Only clearing the quarantine reopens the unit.
13. The certification-average `efficiency_index`, evaluated at two decimal places, must be at most 1.00 at certification time — otherwise `ERR_EFFICIENCY_LIMIT_EXCEEDED`.
14. The governing model variant must be `RELEASED` for build-slot sequencing, build-slot release, unit certification and engineering-change cut-in; for bill-of-materials authoring it must merely not be `OBSOLETE`, because a `DRAFT` variant is precisely where its bill of materials is built up. Otherwise `ERR_MODEL_NOT_RELEASED`.
15. The resolved bill of materials must be non-empty at the relevant sequence index, and a `root_cause_part_id` must appear on the returned unit's as-built bill of materials. This guards build-slot sequencing, engineering-change cut-in and warranty-return analysis, and fails with `ERR_BOM_NOT_EFFECTIVE`.
16. No part on the effective bill of materials may have a `lifecycle_status` of `CHANGE_PENDING` or `OBSOLETE` when a slot is sequenced, and a newly authored bill-of-materials line may not name an `OBSOLETE` part — otherwise `ERR_PART_CHANGE_PENDING`.
17. An engineering change may be cut in only while the target line's `posture` is `STOPPED` — otherwise `ERR_LINE_NOT_STOPPED`.
18. `cut_in_sequence_index` must be strictly greater than the target line's `max_released_sequence_index` — otherwise `ERR_CUT_IN_INDEX_TOO_LOW`.
19. A `replacement_part_id` must be available at cut-in and must not equal `affected_part_id` — otherwise `ERR_REPLACEMENT_PART_REQUIRED`.
20. A `SERVICE_ONLY` part may not be made obsolete while the logical clock is at or before its `service_obligation_until` — otherwise `ERR_SERVICE_OBLIGATION_ACTIVE`.
21. A build slot may be released only when its variant's `family_code` equals the line's `current_family_code` — otherwise `ERR_CHANGEOVER_REQUIRED`.
22. Dock-window separation on delivery-call creation — otherwise `ERR_DOCK_WINDOW_CONFLICT`.
23. Shift-window non-overlap on shift-plan creation — otherwise `ERR_SHIFT_WINDOW_OVERLAP`.
24. Exactly one active shift plan of the line must cover the relevant instant: `planned_start` when sequencing a slot, the logical clock when a changeover is booked by starting the line — otherwise `ERR_NO_SHIFT_COVERAGE`. Coverage is judged on the plan's base window alone — `shift_start` at or before the instant and the instant strictly before `shift_end`, with `overtime_minutes` deliberately excluded — and any count other than exactly one covering `ACTIVE` plan, whether zero or several, raises the error.
25. `sequence_index` is unique per line among build slots whose `status` is `PLANNED`, `SEQUENCED`, `RELEASED` or `BUILT`, enforced when a build slot is created — otherwise `ERR_SEQUENCE_INDEX_TAKEN`. The same uniqueness is re-checked when a slot revived by un-sequencing is sequenced again.
26. A line's `posture` must not be `STOPPED` to sequence a slot, and must be `OPEN` to release one — otherwise `ERR_LINE_POSTURE_BLOCKED`.
27. Every supplier feeding a sequenced module on the effective bill of materials must have a `status` of `APPROVED`, and a new delivery call may not be booked for a `SUSPENDED` supplier — otherwise `ERR_SUPPLIER_NOT_APPROVED`.
28. Every sequenced-module part on the effective bill of materials needs a covering delivery call when a slot is sequenced — otherwise `ERR_SYNC_DELIVERY_MISSING`.
29. Every rolling five-slot window containing the candidate index must satisfy the option-load cap when a slot is sequenced — otherwise `ERR_OPTION_LOAD_WINDOW_EXCEEDED`.
30. The presentation allocation must fit at every station named by the effective bill of materials when a slot is sequenced — otherwise `ERR_PRESENTATION_SLOTS_EXHAUSTED`.
31. The covering shift plan's recomputed `committed_labor_minutes` must not exceed its `available_labor_minutes` when a slot is sequenced — otherwise `ERR_LABOR_CAPACITY_EXCEEDED`.
32. Natural-key uniqueness: `line_code`, `model_code`, `supplier_code` and `part_number` are unique globally, and `station_code` and `position_index` are each unique within a line. Violations on line, station, model-variant, supplier and part creation are rejected with `ERR_DUPLICATE_CODE`.

Two consequences of this ordering deserve emphasis. First, sequencing a build slot walks rules 14, 15, 16 and then 24 through 31 in exactly that order, so an operator whose slot fails several checks always sees the lowest-numbered one — a slot whose variant is still `DRAFT` reports `ERR_MODEL_NOT_RELEASED` even if its labour would also have overflowed. Second, because the ladder is global, a stale concurrency token (rule 7) always beats a business-rule violation such as a duplicate code (rule 32), and a role violation (rule 2) always beats a missing foreign key (rule 5).

### 2.9. Nested Reads and Left-to-Right Path Resolution

The API is flat, but a handful of endpoints hang a sub-collection off a parent identifier — the stations of a line, the shift plans of a line, the quality tests of a unit, the warranty metrics of a part. For those, identifiers in the path are resolved strictly left to right, and the first identifier that does not resolve determines the 404. Reading the quality tests of a non-existent unit yields `ERR_PRODUCTION_UNIT_NOT_FOUND`; reading the shift plans of a non-existent line yields `ERR_LINE_NOT_FOUND`. Path resolution always precedes body and query validation of foreign keys.

### 2.10. Line Posture: The Master Gate

Each line exposes a computed `posture` that acts as the single gate over the operations its children may perform. It is derived, never supplied, and is recomputed after every mutation that touches the line's stations, its build slots, its shift plans or its `operating_mode`. The derivation is evaluated in this order:

- If `operating_mode` is `STOPPED`, `posture` is `STOPPED`.
- Otherwise, if `free_slot_pct` is strictly less than 20.00, `posture` is `CONSTRAINED`.
- Otherwise, if any station on the line has a `presentation_slots_used` equal to its `presentation_slot_capacity` while that capacity is greater than zero, `posture` is `CONSTRAINED`.
- Otherwise `posture` is `OPEN`.

`presentation_slots_total` is the sum of `presentation_slot_capacity` over the line's stations and `presentation_slots_committed` is the sum of `presentation_slots_used` over those same stations. From those two, `free_slot_pct` is one hundred times the difference between total and committed, divided by the total, rounded to two decimal places half up. When `presentation_slots_total` is zero, `free_slot_pct` is 0.00 by definition — an empty denominator is treated as fully committed, which means a freshly created line that has no stations yet is `CONSTRAINED`, not `OPEN`.

The gate is asymmetric on purpose. A `CONSTRAINED` line still permits build slots to be sequenced — planning ahead into a tight line is legitimate — but blocks any slot from being released to the floor. A `STOPPED` line blocks both. Both refusals carry `ERR_LINE_POSTURE_BLOCKED`.

### 2.11. Cascade Discipline and Exact Reversal

Many operations in this system mutate more than one entity. Where they do, the cascade is part of the contract, not an implementation detail, and it must run to its full depth within the same request. Cutting in an engineering change, for instance, reaches four levels deep: a bill-of-materials line is superseded, the outgoing part acquires a service obligation, that part's future dock calls are cancelled, and build slots pinned to those cancelled calls are un-sequenced. A missed delivery detected by a checkpoint reaches the same depth through a different chain: the supplier is scored, the score demotes the supplier's `status`, the demotion cancels that supplier's remaining scheduled calls, and each cancellation un-sequences its dependent slot.

Two conservation invariants govern the reversals:

- **Presentation-slot conservation.** Whatever per-station `slot_units` a build slot charged at sequencing time is recorded on that slot, and un-sequencing gives back exactly those recorded amounts to exactly those stations — never a recomputed figure. A line's committed total therefore always equals the sum of the live slots' charges, no matter how many times slots have been sequenced and un-sequenced against a changing bill of materials.
- **Defect-attribution conservation.** A warranty return that is withdrawn gives back exactly the counter increments its analysis applied: the charged part's `field_failure_count` comes back down by one, and a supplier quality charge is refunded in full.

Wherever a cascade mutates an entity, that entity's own `updated_at` and `version` follow the rules of §2.5.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Line: Stations, Tooling and Stoppages

A plant administrator brings a new assembly line into existence by declaring its `line_code` — a human identifier of between 1 and 16 characters that must be unique across all lines, colliding with `ERR_DUPLICATE_CODE` — together with its `takt_seconds` (the per-station takt time in seconds, at least 1), its `option_load_limit_pct` (the percentage of theoretical maximum option content the line can absorb in one rolling window, greater than zero and at most 100), its `baseline_headcount` (the headcount that percentage is calibrated for, at least 1), and its `current_family_code`, naming the product family the line is currently tooled for. A newly created line comes up with `operating_mode` `RUNNING`, a null `stop_reason`, a `changeover_count` of 0, a `checkpoint_index` of 0, a `max_released_sequence_index` of 0, `presentation_slots_total` and `presentation_slots_committed` both 0, a `free_slot_pct` of 0.00 and therefore — per §2.10 — a `posture` of `CONSTRAINED`.

Stations are added to the line one at a time, each carrying the `line_id` it sits on, a `station_code` unique within that line, a `position_index` of at least 1 that is likewise unique within the line and ascends in flow order, a `presentation_slot_capacity` counting the line-side presentation slots physically available there (which may be zero), and a `station_cycle_seconds` recording the work content at that station in seconds (at least 1). A station begins with `presentation_slots_used` at 0. Creating a station immediately re-derives the line's `presentation_slots_total`, `free_slot_pct` and `posture`, and advances the line's `version`.

Stopping the line is available to a line operator or a plant administrator and is legal only while `operating_mode` is `RUNNING`; the transition `RUNNING → STOPPED` records the supplied `reason` — a required, non-empty string — into `stop_reason`, drives `posture` to `STOPPED`, and advances the line's `version` by one. While the line is stopped, sequencing and releasing build slots are both refused with `ERR_LINE_POSTURE_BLOCKED` — and, as §3.8 explains, a stopped line is exactly the condition an engineering change needs in order to be cut in.

Starting the line reverses `STOPPED → RUNNING`, clears `stop_reason` back to null, re-derives `posture` from `free_slot_pct` and per-station saturation, and advances `version`. The start request may optionally carry a `to_family_code`, and this is where model changeover is booked. When `to_family_code` is supplied **and differs** from the line's `current_family_code`, three things happen together: `current_family_code` is replaced by the supplied value, `changeover_count` is incremented by one, and eighteen changeover minutes are added to the `changeover_minutes` of the line's active shift plan whose window contains the logical clock, which in turn re-derives that plan's `committed_labor_minutes`. If no active plan of the line covers the logical clock, the entire start is rejected with `ERR_NO_SHIFT_COVERAGE` — the line stays stopped and nothing is written. When `to_family_code` is absent, or is supplied but equal to the current `current_family_code`, no changeover is recorded at all and `changeover_count` is left unchanged.

Reading a line returns its recomputed `posture`, `free_slot_pct` and `max_released_sequence_index` alongside the `version` a client needs for `expected_line_version`. The `max_released_sequence_index` is the highest `sequence_index` among the line's build slots whose `status` is `RELEASED` or `BUILT`, and 0 when the line has none.

### 3.2. Product Definition and the Living Bill of Materials

A **model variant** is one appliance model plus one option build code. A plant administrator creates it with its `model_code` (unique across all variants), its `family_code` (which is what drives changeover on the line), a required `option_codes` array of option-code strings — which may be empty, but not omitted — carried purely for information, an `option_content_points` value between 0 and 10 inclusive expressing the option-complexity load one unit of this variant places on a single sequence position, a `labor_minutes` figure strictly greater than zero for direct labour per unit, and a `functional_cycle_count_required` of at least 1. Five further fields describe its test limits and may be supplied at creation: `requires_leak_test`, which defaults to false and is true only for water-bearing appliances; `hipot_leakage_ma_limit`, the electrical-safety leakage-current limit in milliamps, strictly greater than zero; `leak_limit_ml_per_min`, the water-leak limit in millilitres per minute, which is required when `requires_leak_test` is true and null otherwise; `energy_kwh_limit`, the certification limit for annual energy consumption in kilowatt-hours, strictly greater than zero; and `water_liters_limit`, the certification limit for per-cycle water consumption in litres, strictly greater than zero.

A variant's `status` begins at `DRAFT`. Release, restricted to a plant administrator and legal only from `DRAFT`, moves it `DRAFT → RELEASED` and advances its `version`; only then may build slots of that variant be sequenced. Obsoleting, legal only from `RELEASED`, moves it `RELEASED → OBSOLETE` and advances its `version`; afterwards, further build-slot sequencing, further bill-of-materials authoring and certification of units of that variant are all refused with `ERR_MODEL_NOT_RELEASED`, while units already released keep building through to shipment.

The bill of materials is the many-to-many junction between variants and parts, keyed by position. An engineering lead or a plant administrator authors a line by supplying the `model_variant_id` it belongs to, the `part_id` consumed, the `station_id` where that part is presented, the `bom_position_code` naming the stable position inside the variant (for instance `DOOR-ASSY`), the `qty_per_unit` pieces consumed per appliance (a positive quantity of at least 1), an `effective_from_sequence` of at least 1 that defaults to 1 and names the first build-slot `sequence_index` the line applies to, and the mandatory `expected_model_variant_version` of §2.7. Authoring is legal while the variant is `DRAFT` or `RELEASED` and refused once it is `OBSOLETE`, and that variant-status check happens **after** the version check, so a client holding a stale view of an obsoleted variant sees `ERR_STALE_MODEL_VARIANT_VERSION` rather than `ERR_MODEL_NOT_RELEASED`. A line may not name a part whose `lifecycle_status` is `OBSOLETE`; that attempt is refused with `ERR_PART_CHANGE_PENDING`.

A new line arrives with `status` `ACTIVE`, a null `superseded_by_bom_line_id` and a null `created_by_change_id` — the latter stays null for every manually authored line and is filled in only for lines minted by a cut-in. Authoring also supersedes: any existing `ACTIVE` line for the same combination of `model_variant_id` and `bom_position_code` whose `effective_from_sequence` is greater than or equal to the new line's becomes `SUPERSEDED`, with its `superseded_by_bom_line_id` pointing at the new line. The variant's `version` then advances by one.

**Resolving the effective bill of materials** at a given sequence index is the operation that makes cut-in tracking work, and it is used in two distinct flavours. Candidates for a variant at index S are its bill-of-materials lines whose `effective_from_sequence` is less than or equal to S. Within each `bom_position_code`, the winner is the candidate with the greatest `effective_from_sequence`; ties are broken by `created_at` descending and then by `id` descending. Positions whose only candidates are filtered out contribute nothing, and a resolution that yields zero positions is `ERR_BOM_NOT_EFFECTIVE`. The boundary is inclusive: a line minted with an `effective_from_sequence` of 5 does not govern a slot at `sequence_index` 4 — there the earlier line still wins — and does govern a slot at `sequence_index` 5.

The two flavours differ only in which lines are candidates. The **production-effective** resolution considers only lines whose `status` is `ACTIVE`, and it is the one used by build-slot sequencing, by presentation allocation and by engineering-change cut-in: a superseded line can never be built again. The **as-built** resolution considers lines whose `status` is `ACTIVE` or `SUPERSEDED`, and it is used when a warranty return is analysed, so that a part cut out of production last month is still a legitimate root cause for an appliance built before the cut-in.

Bill-of-materials lines can be listed and filtered by `model_variant_id`, `part_id`, `station_id`, `superseded_by_bom_line_id`, `created_by_change_id`, `bom_position_code` and `status`, and by `effective_at_sequence`, which applies the resolution above at the supplied index — the production-effective flavour when `status` is omitted or given as `ACTIVE`, and the as-built flavour when superseded lines are requested through `status` equal to `SUPERSEDED`. When `effective_at_sequence` is supplied, `status` serves only to choose the flavour and is not additionally applied as a post-filter to the winners, and if `model_variant_id` is omitted the resolution is run once per variant that owns any bill-of-materials line and the winners are unioned; the remaining filters are then applied to that resolved set.

### 3.3. Synchronous Supply: Suppliers, Parts and Dock Call-Offs

Suppliers are registered by a plant administrator with a globally unique `supplier_code`, a legal `name` and a `sync_window_minutes` recording the nominal synchronous-delivery window length the supplier commits to (at least 1 minute, informational only). A new supplier starts `APPROVED` with an `on_time_score` of 100.00 and with `delivered_on_time_count`, `delivered_late_count`, `missed_count` and `quality_penalty_count` all at zero.

The `on_time_score` is not accumulated incrementally but replayed from those four counters. It starts from 100.00, gains 2 points for each on-time delivery counted in `delivered_on_time_count`, loses 8 points for each late delivery in `delivered_late_count`, loses 20 points for each miss in `missed_count`, and loses 10 points for each warranty defect charged against the supplier in `quality_penalty_count`. The result is clamped into the range from 0.00 to 100.00, and the clamp is applied **before** the band lookup, so a supplier cannot bank credit above 100.00 in order to survive future misses. The supplier's `status` is then re-derived from the clamped score: at least 60.00 is `APPROVED`, at least 40.00 is `PROBATION`, and anything below that is `SUSPENDED`. The boundary is worth spelling out: two missed calls bring a fresh supplier to exactly 60.00, which is still `APPROVED`, and no cancellation cascade fires; a third miss brings it to 40.00, which is `PROBATION`, and the cascade does fire.

Whenever a supplier enters `PROBATION` or `SUSPENDED` from `APPROVED`, every remaining delivery call of that supplier still in `SCHEDULED` is cancelled with a `cancel_reason` of `SUPPLIER_PROBATION`, and every build slot pinned to one of those calls and still `SEQUENCED` is un-sequenced back to `PLANNED` with the complete reversal set described in §3.5.

Parts are registered with a globally unique `part_number`, the `supplier_id` of the supplier that ships them, an `is_sequenced_module` flag that defaults to false, and a `line_side_max_units` of at least 1 giving how many units of the part fit in one line-side presentation slot. A part starts with `lifecycle_status` `ACTIVE`, a `field_failure_count` of 0, a `cohort_failure_rate_per_1000` of 0.00 and a null `service_obligation_until`. A part flagged `is_sequenced_module` is delivered in build sequence: it consumes no line-side presentation slots at all, but it requires a covering dock call at sequencing time. The part catalogue can be filtered by `supplier_id`, `lifecycle_status` and `is_sequenced_module`, and a `SupplierPortal` caller may filter only by its own `supplier_id`.

A production planner or plant administrator books a **delivery call** by supplying the `supplier_id` called off, the `part_id` or sequenced module wanted, the `station_id` that serves as the line-side drop point, a `window_start` and a `window_end` bounding the delivery window, and a `sequenced_qty` of at least 1 counting the modules in the drop. The window is half-open — `window_start` is inclusive and `window_end` is exclusive — and `window_end` must be strictly after `window_start`. The call starts `SCHEDULED` with a null `arrived_at`, a null `lateness_minutes` and a null `cancel_reason`.

Two rules constrain booking. The dock at a station must have ten clear minutes on either side of every delivery: the new call's window, padded by ten minutes before `window_start` and ten minutes after `window_end`, may not intersect the unpadded window of any other call at the same station whose `status` is `SCHEDULED`, `ARRIVED_ON_TIME` or `ARRIVED_LATE`; cancelled and missed calls free their dock slot. A collision is `ERR_DOCK_WINDOW_CONFLICT`. And a `SUSPENDED` supplier may not be called off at all, which is `ERR_SUPPLIER_NOT_APPROVED`.

Arrival is recorded through the supplier portal and only by the supplier that owns the call. The request carries the `arrived_at` instant. An `arrived_at` strictly before `window_end` takes the call `SCHEDULED → ARRIVED_ON_TIME` with `lateness_minutes` of 0 — arriving early counts as on time — increments `delivered_on_time_count`, adds 2 points to `on_time_score` capped at 100.00, and re-derives the supplier's `status`. An `arrived_at` at or after `window_end` takes the call `SCHEDULED → ARRIVED_LATE`; because the window is half-open, arriving at exactly `window_end` is late. `lateness_minutes` is then the elapsed time from `window_end` to `arrived_at`, expressed in seconds, divided by sixty and rounded up to the next whole minute. `delivered_late_count` is incremented, 8 points are subtracted from `on_time_score` with a floor of 0.00, and the supplier's `status` is re-derived — a drop below 60.00 triggers exactly the cancellation cascade described above.

A planner or administrator may cancel a `SCHEDULED` call outright. That takes it `SCHEDULED → CANCELLED` with `cancel_reason` `PLANNER`, and every build slot whose pinned call it was and which is still `SEQUENCED` is un-sequenced to `PLANNED`, replaying the full reversal: presentation slots released, shift labour recomputed and line posture re-derived. The system itself cancels scheduled calls in two other situations, distinguished by `cancel_reason`: `SUPPLIER_PROBATION` when the supplier has been demoted, and `PART_SERVICE_ONLY` when the part has been cut out of production. In both cases the dependent `SEQUENCED` slots receive the same full reversal.

Delivery calls can be listed and filtered by `supplier_id`, `part_id`, `station_id`, `status` and `cancel_reason`. A supplier-portal caller sees only its own calls, and a single-call read exposes the computed `lateness_minutes` and the `cancel_reason`.

### 3.4. Staffing the Shifts

Seasonal demand and retail promotion cycles are absorbed in this system by moving one number: the `planned_headcount` on a shift plan. A production planner or plant administrator creates a plan for a line by supplying the `line_id`, the `shift_date` as a `YYYY-MM-DD` calendar date in UTC, the `shift_code`, a `planned_headcount` of at least 1, the absolute `shift_start` and `shift_end` instants, the mandatory `expected_line_version` of §2.7, and optionally `overtime_minutes` between 0 and 120 inclusive (defaulting to 0).

`shift_code` is one of `A`, `B` or `C`, and it fixes the base window: `A` runs 06:00 to 14:00 UTC, `B` runs 14:00 to 22:00 UTC, and `C` runs 22:00 to 06:00 UTC of the following day. The supplied `shift_start` must equal the `shift_date` at the base start hour of the declared `shift_code`, and the supplied `shift_end` must equal the corresponding base end hour — with `C` wrapping into the next calendar day — and must be strictly after `shift_start`. Any mismatch is `ERR_INVALID_REQUEST`.

Three labour figures are derived on every plan. `available_labor_minutes` is the shift's 480 base minutes plus its `overtime_minutes`; the line runs a single crew, so `planned_headcount` is emphatically **not** a factor in available minutes — its only role in this system is to scale the option-load window cap of §3.5. `unit_labor_minutes` is the sum of `labor_minutes_snapshot` over the plan's build slots whose `status` is `SEQUENCED`, `RELEASED` or `BUILT`. `changeover_minutes` is eighteen minutes for each family boundary among those same slots, taken in ascending `sequence_index` order — a boundary being any slot whose variant's `family_code` differs from the previous slot's, plus the first slot when its family differs from the line's `current_family_code` — plus any changeover minutes already booked onto the plan by a line start, as described in §3.1.

`committed_labor_minutes` then applies a fatigue multiplier. Let the gross total be `unit_labor_minutes` plus `changeover_minutes`. The multiplier is 1.00 when the gross total is at most 300 minutes, 1.05 when it is at most 450 minutes, and 1.12 above that. The committed figure is the gross total multiplied by that multiplier, rounded up to a whole minute once, at the end. Both the tier selection and the multiplication use the **gross** total, changeover minutes included: a plan holding a 150-minute unit of one family at index 1 and a 145-minute unit of another family at index 2 on a line tooled for the first family has `unit_labor_minutes` of 295 and `changeover_minutes` of 18, so the gross total is 313; because 313 exceeds the 300-minute tier boundary the multiplier is 1.05, and the committed figure is 313 multiplied by 1.05, which is 328.65, rounded up to 329. Choosing the tier from the 295 unit minutes alone, or applying the multiplier to the unit minutes and adding changeover afterwards, both yield different answers and are wrong. The eighteen changeover minutes are frequently what pushes a plan over the tier boundary in the first place.

A plan starts with `status` `ACTIVE`. Creating a new plan for a combination of `line_id`, `shift_date` and `shift_code` that already has an `ACTIVE` plan supersedes it: the old plan moves `ACTIVE → SUPERSEDED`, every build slot whose `shift_plan_id` was the old plan is repointed to the new one, the new plan's `unit_labor_minutes`, `changeover_minutes` and `committed_labor_minutes` are computed from the repointed slots, and the superseded plan keeps its last computed values frozen. Any eighteen-minute changeover blocks a line start had booked onto the old plan are **not** carried across: the new plan's `changeover_minutes` counts only the family boundaries of the repointed slots until a further line start books more onto it. The line's `version` advances by one.

Two `ACTIVE` plans on the same line may not overlap in time. The comparison uses each plan's effective window — from `shift_start` up to but not including `shift_end` plus `overtime_minutes` — on absolute timestamps, so a `C` shift crossing midnight is compared correctly against the next day's `A` shift. Touching endpoints are allowed: a plan ending at exactly the instant another begins does not overlap. An intersection is `ERR_SHIFT_WINDOW_OVERLAP`. The one plan excluded from this comparison is the plan the new one supersedes, that is, the `ACTIVE` plan for the same `line_id`, `shift_date` and `shift_code`; every other `ACTIVE` plan on the line is compared.

Plans of a line can be listed and filtered by `shift_date`, `shift_code` and `status`, and a single-plan read exposes `unit_labor_minutes`, `changeover_minutes`, `committed_labor_minutes` and `available_labor_minutes` together.

### 3.5. Mixed-Model Sequencing: Option Load, Presentation Slots and Labour

A **build slot** is one position in the mixed-model build sequence of one line. A production planner or plant administrator creates it by naming the `line_id` it is scheduled on, the `model_variant_id` that gets built in it, its `sequence_index` (at least 1) and its `planned_start` instant, which is what later selects both the covering shift plan and the covering delivery call. The slot arrives with `status` `PLANNED`, and at that moment it consumes nothing: `shift_plan_id`, `sync_delivery_call_id`, `option_points_snapshot` and `labor_minutes_snapshot` are all null, `presentation_allocations` is empty and `allocated_slot_units` is 0. What creation does enforce is uniqueness of `sequence_index` across the line's live slots — those in `PLANNED`, `SEQUENCED`, `RELEASED` or `BUILT` — with a collision reported as `ERR_SEQUENCE_INDEX_TAKEN`.

**Sequencing** is the single most heavily guarded operation in the plant, and it belongs exclusively to a production planner. It moves the slot `PLANNED → SEQUENCED` and walks the checks of §2.8 in their ladder order: the variant must be `RELEASED`; the production-effective bill of materials must resolve to at least one `bom_position_code`; no part on that bill may be `CHANGE_PENDING` or `OBSOLETE`; exactly one `ACTIVE` shift plan of the line must cover `planned_start`; the `sequence_index` must still be free on the line; the line's `posture` must not be `STOPPED`; every supplier feeding a sequenced module on that bill must be `APPROVED`; every sequenced-module part on that bill must have a covering delivery call; every rolling window of five sequence indexes containing this one must satisfy the option-load cap; the presentation allocation must fit at every station involved; and the covering plan's recomputed `committed_labor_minutes` must not exceed its `available_labor_minutes`. Nothing at all is written if any of those fires.

A **covering delivery call** for a sequenced module is one with the same `part_id` and the same `station_id` as the bill-of-materials line, whose `status` is `SCHEDULED`, `ARRIVED_ON_TIME` or `ARRIVED_LATE`, and whose window contains the slot's `planned_start` — that is, `window_start` at or before `planned_start`, and `planned_start` strictly before `window_end`. A sequenced-module part with no such call fails with `ERR_SYNC_DELIVERY_MISSING` before any allocation arithmetic runs. When several calls satisfy the test for one bill-of-materials line, the one with the earliest `window_start`, then earliest `created_at`, is the one selected; and when the effective bill carries more than one sequenced module, every one of them must be covered but the slot's `sync_delivery_call_id` is pinned to the call selected for the first such bill-of-materials line in the allocation order defined below — ascending station `position_index`, then ascending `bom_position_code`.

The **option-load window cap** exists because mixed-model sequencing must not bunch option-heavy appliances together, which would starve the stations that carry the option content. For a candidate slot at index S, every rolling window of five consecutive indexes that contains S must satisfy the cap — that is, the windows running from four indexes before S through S, then three before S through one after, and so on up to S through four indexes after S: five windows in all. The points in a window are the sum of `option_points_snapshot` over the line's slots whose `sequence_index` falls inside the window and whose `status` is `SEQUENCED`, `RELEASED` or `BUILT`, plus the candidate variant's own `option_content_points`. The cap is the product of four factors — the five-slot window length, the line's `option_load_limit_pct` divided by one hundred, the maximum ten option points a single slot may carry, and a staffing factor — with the result rounded **down** to a whole number, that rounding-down applied exactly once and only to the finished product. The staffing factor is the smaller of 1 and the ratio of the covering `ACTIVE` plan's `planned_headcount` to the line's `baseline_headcount`, rounded to four decimal places before it is multiplied in. The slot is admissible only when every one of the five windows is at or below the cap; otherwise `ERR_OPTION_LOAD_WINDOW_EXCEEDED`.

An example pins the arithmetic. On a line whose `option_load_limit_pct` is 63.00 and whose `baseline_headcount` is 20, covered by a plan staffing 18 operators, the staffing factor is 0.9000; five times 0.63 times ten times 0.9000 is 28.35, and rounding down once gives a cap of 28. A window totalling exactly 28 option points is admitted; a window totalling 29 is rejected. With the same line fully staffed at 20 operators the factor is 1.0000 and the cap is 31, because five times 0.63 times ten is 31.5 and rounding down once gives 31. Rounding down an intermediate factor, dropping the rounding-down entirely, or applying the staffing factor per slot rather than per window all produce different and incorrect caps.

**Line-side presentation** is allocated at the same moment. For every `ACTIVE` bill-of-materials line on the production-effective bill at the slot's `sequence_index`, the slot charges a number of presentation units to that line's station. That number is zero when the part is a sequenced module *and* a covering delivery call exists — synchronous supply bypasses line-side storage entirely. Otherwise it is the `qty_per_unit` multiplied by the twenty units of build the plant presents at a time, divided by the part's `line_side_max_units`, with the whole quotient rounded up to a whole number; a `qty_per_unit` of 2 against a `line_side_max_units` of 24 therefore charges 2 units, because twice twenty is forty, forty divided by twenty-four is one and two-thirds, and rounding up gives 2. Allocation walks the bill-of-materials lines in ascending station `position_index` and then ascending `bom_position_code`, adding each charge to that station's `presentation_slots_used`. The first station at which the existing `presentation_slots_used` plus the new charge would exceed its `presentation_slot_capacity` aborts the entire sequencing attempt with `ERR_PRESENTATION_SLOTS_EXHAUSTED`, and **no** station is charged.

When all checks pass, sequencing pins the slot's state so that later reversals are exact. `shift_plan_id` is set to the covering plan, `sync_delivery_call_id` to the selected sequenced-module call (or left null when the variant carries no sequenced module), `option_points_snapshot` to the variant's `option_content_points` and `labor_minutes_snapshot` to its `labor_minutes` as they stand at that moment. `presentation_allocations` records one object per charged station, each carrying that `station_id` and its `slot_units`, and `allocated_slot_units` records their sum. Each station's `presentation_slots_used` is then increased by its charge in ascending `position_index` order, the line's `presentation_slots_committed`, `free_slot_pct` and `posture` are re-derived, and the covering plan's `unit_labor_minutes`, `changeover_minutes` and `committed_labor_minutes` are recomputed.

**Un-sequencing** by a production planner moves the slot `SEQUENCED → PLANNED` and reverses all of it: each station's `presentation_slots_used` is reduced by exactly the `slot_units` recorded for it in `presentation_allocations`; `shift_plan_id`, `sync_delivery_call_id`, `option_points_snapshot` and `labor_minutes_snapshot` return to null, `presentation_allocations` to empty and `allocated_slot_units` to 0; the former plan's three labour figures are recomputed from its remaining slots; and the line's `presentation_slots_committed`, `free_slot_pct` and `posture` are re-derived. The identical `SEQUENCED → PLANNED` reversal runs automatically, with no operator involved, whenever the slot's pinned `sync_delivery_call_id` is cancelled for any reason at all — planner cancellation, supplier demotion or a part going service-only.

A slot that never got sequenced can also expire: a slot still `PLANNED` whose `planned_start` has fallen behind the logical clock is taken `PLANNED → CANCELLED` by the checkpoint sweep of §3.9, and its `sequence_index` is thereby freed for reuse by a new slot. Build slots can be listed and filtered by `line_id`, `model_variant_id`, `shift_plan_id`, `sync_delivery_call_id` and `status`, and a single-slot read exposes the pinned snapshots together with `presentation_allocations` and `allocated_slot_units`.

### 3.6. Release, Assembly and Shipment

Releasing a slot to the floor belongs exclusively to a line operator and takes the slot `SEQUENCED → RELEASED`. Three conditions guard it: the line's `posture` must be `OPEN`, so a `CONSTRAINED` or `STOPPED` line refuses with `ERR_LINE_POSTURE_BLOCKED`; the variant's `family_code` must equal the line's `current_family_code`, or the release is refused with `ERR_CHANGEOVER_REQUIRED` because the line is tooled for a different family; and the variant's `status` must still be `RELEASED`, or `ERR_MODEL_NOT_RELEASED` applies.

Release mints a **production unit**, the physical appliance. Its `build_slot_id` points back at the releasing slot; its `built_at_sequence_index` copies the slot's `sequence_index` and is the index against which the historical bill of materials will later be resolved for warranty attribution; and its `serial_number` is deterministic — the line's `line_code`, then a hyphen, then the `sequence_index` zero-padded to six digits, so slot 4 on line `L1` yields `L1-000004`. The unit starts with `assembly_status` `IN_STATION`, `quality_status` `PENDING`, `rework_count` 0, and null `provisional_efficiency_index`, `efficiency_index` and `certification_tier`. Those fields, together with `build_slot_id`, `serial_number`, `built_at_sequence_index` and the identity and audit fields of §2.5, are the whole of a production unit's representation: the unit carries no `model_variant_id` of its own, and no production-unit response body exposes one. The governing model variant is always reached indirectly, through the unit's `build_slot_id` and that build slot's `model_variant_id` — that is how the variant is found for quality-test limits and applicability, for certification, and for resolving the as-built bill of materials at `built_at_sequence_index`. The line's `max_released_sequence_index` is recomputed, and the presentation slots the build slot pinned stay committed, because the unit is now the thing consuming them. The `data` of the release response is that minted production unit, not the build slot.

A production unit carries **two independent status dimensions**, and this independence is deliberate. `assembly_status` runs over `IN_STATION`, `ASSEMBLED`, `REWORK` and `SHIPPED`. `quality_status` runs over `PENDING`, `SAFETY_PASSED`, `GATED`, `CERTIFIED` and `QUARANTINED`. They advance separately, and only two guards couple them.

Completing assembly, a line-operator action, moves `IN_STATION → ASSEMBLED` provided the unit's `quality_status` is not `QUARANTINED` — a quarantined unit is refused with `ERR_UNIT_QUARANTINED`. The quality dimension is left entirely untouched. As a bubble-up side effect, the owning build slot moves `RELEASED → BUILT`: the slot is closed, but its presentation slots stay committed until the appliance actually leaves.

Shipping, also a line-operator action, is where the dimensions do couple. It moves `ASSEMBLED → SHIPPED` and requires `quality_status` to be exactly `CERTIFIED`; anything else is `ERR_INVALID_STATE`. Shipping is the moment line-side capacity is finally given back: each station named in the slot's `presentation_allocations` has its `presentation_slots_used` reduced by the recorded `slot_units`, and the line's `presentation_slots_committed`, `free_slot_pct` and `posture` are re-derived; the slot itself is left exactly as it was, keeping its `status` `BUILT` and keeping `presentation_allocations` and `allocated_slot_units` on record as the historical charge. A shipped unit is also the only kind of unit eligible for a warranty return. Production units can be listed and filtered by `build_slot_id`, `assembly_status`, `quality_status` and `certification_tier`.

### 3.7. Quality Gates, Quarantine and Efficiency Certification

Only a quality inspector records measurements against a unit, and each measurement is an append-only quality test carrying a `test_type` — one of `ELECTRICAL_SAFETY`, `LEAK`, `FUNCTIONAL_CYCLE`, `ENERGY` or `WATER` — and a non-negative `measured_value`, in milliamps for electrical safety, millilitres per minute for leak, completed cycles for the functional test, kilowatt-hours for energy and litres for water. The server snapshots the governing limit onto the record as `limit_value`, taken from the model variant's `hipot_leakage_ma_limit`, `leak_limit_ml_per_min`, `functional_cycle_count_required`, `energy_kwh_limit` or `water_liters_limit` according to the `test_type`, so that later re-limits of the variant never rewrite history. The test's `status` is `RECORDED`. Recording a test writes the test record itself; the unit's own `updated_at` and `version` move only when the recording actually changes the unit's `assembly_status`, `quality_status` or `rework_count`, so a plain `ENERGY` or `WATER` measurement leaves the unit's `version` untouched.

The test's `result` is computed, not supplied, and one direction is inverted. For `ELECTRICAL_SAFETY` and `LEAK` the result is `PASS` when `measured_value` is less than or equal to `limit_value`. For `FUNCTIONAL_CYCLE` it is `PASS` when `measured_value` is greater than or equal to `limit_value`, because there the limit is a floor of cycles the appliance must complete rather than a ceiling. Otherwise the result is `FAIL`. `ENERGY` and `WATER` tests are never pass/fail at all: their `result` is always `MEASURED`, and they never quarantine a unit — they are scored at certification time instead.

Applicability and ordering are checked before anything is written. A `LEAK` test is only meaningful for a water-bearing appliance, so recording one against a variant whose `requires_leak_test` is false is refused with `ERR_TEST_NOT_APPLICABLE`, as is a `WATER` test against a variant with no `water_liters_limit`. Ordering is then enforced with `ERR_QUALITY_GATE_ORDER`: `ELECTRICAL_SAFETY` must come first — which is to say it carries no `quality_status` precondition of its own and is accepted from any state the unit is not quarantined in, `GATED` and `CERTIFIED` included — `LEAK` and `FUNCTIONAL_CYCLE` require a `quality_status` of `SAFETY_PASSED` or `GATED`, and `ENERGY` and `WATER` require a `quality_status` of `GATED`.

Passing tests walk the quality dimension forward. An `ELECTRICAL_SAFETY` test with a `PASS` result moves the unit `PENDING → SAFETY_PASSED`, which is what unlocks leak and functional-cycle testing, and leaves the quality dimension exactly where it is when the unit has already moved past `PENDING`. The unit then moves `SAFETY_PASSED → GATED` as soon as a `FUNCTIONAL_CYCLE` test with `PASS` exists and — only when the variant's `requires_leak_test` is true — a `LEAK` test with `PASS` also exists, both with `status` `RECORDED`. Reaching `GATED` is what unlocks energy and water measurement and, in turn, certification.

Any test whose `result` is `FAIL` quarantines the unit in a single mutation, from whichever quality state it was in: `PENDING → QUARANTINED`, `SAFETY_PASSED → QUARANTINED`, `GATED → QUARANTINED` or, when a later safety re-test fails against an already-certified appliance, `CERTIFIED → QUARANTINED`. In the same mutation the assembly dimension moves to `REWORK` — `IN_STATION → REWORK` or `ASSEMBLED → REWORK` — and `rework_count` is incremented by one; a unit that has already `SHIPPED` keeps `assembly_status` `SHIPPED` while still being quarantined and still having `rework_count` incremented. When the unit was already `ASSEMBLED`, its build slot stays `BUILT`; the rework happens off the slot's books.

Clearing the quarantine is a quality-inspector action that may carry an explanatory `note`. It requires the unit to be in `REWORK` on the assembly dimension and `QUARANTINED` on the quality dimension, and it does three things: every quality test of that unit whose `result` is `FAIL` and whose `status` is still `RECORDED` becomes `VOIDED`; the quality dimension returns `QUARANTINED → PENDING`; and the assembly dimension returns `REWORK → IN_STATION`. Voided tests leave both the gate evaluation and the efficiency input set entirely, which means the gate chain must be walked again from `PENDING` — this cycle can repeat as often as the floor needs it to, and `rework_count` accumulates across every pass.

**Efficiency certification** turns energy and water measurements into a single index. Each `ENERGY` or `WATER` test whose `status` is `RECORDED` contributes a ratio: its `measured_value` divided by its `limit_value`. The evaluation order is pinned in four steps, and it is observable. First, each individual test's ratio is rounded to two decimal places, half up. Second, the rounded ratios are averaged **per test type**, to four decimal places, half up, giving an energy mean and a water mean. Third, the two means are weighted and summed: six tenths of the energy mean plus four tenths of the water mean. Fourth, that weighted sum is rounded to two decimal places, half up, and the result is the index. Rounding the ratios before weighting is mandatory; weighting the unrounded ratios and rounding only once at the end is a different calculation that yields a different certification tier. With a single energy test measuring 413.96 against a limit of 400.00 and a single water test measuring 168.98 against a limit of 200.00, the pinned order gives ratios of 1.03 and 0.84, a weighted sum of 0.954, and an index of 0.95 — tier `A`. Weighting the unrounded 1.0349 and 0.8449 would give 0.9589 and an index of 0.96 — tier `B` — which is wrong.

The tier is then read off the two-decimal index: an index of at most 0.80 is `A_PLUS`, at most 0.95 is `A`, and at most 1.00 is `B`. An index above 1.00 is not certifiable at all.

The same four-step calculation is exposed in two variants over two different input sets. The **provisional** variant, published as `provisional_efficiency_index` on every unit read whatever the `quality_status` is — certified units included, where it sits alongside the frozen `efficiency_index` — uses for each of `ENERGY` and `WATER` only the single most recent `RECORDED` test of that type, ordered by `created_at` descending with `id` descending as the tie-break; averaging a single rounded ratio is of course the identity, so the provisional index moves with the latest measurement. It is null until at least one `RECORDED` test of each of the two types exists. The **certification** variant uses **all** `RECORDED` tests of each type and genuinely averages them; it is computed only by certification and written into `efficiency_index` and `certification_tier`. The two diverge whenever a type has been measured more than once: with energy tests of 420.00 and 380.00 against a 400.00 limit and a single water test of 184.00 against a 200.00 limit, the provisional index uses only the later energy test, giving an energy mean of 0.9500, a water mean of 0.9200 and an index of 0.94 — tier `A`; the certification variant averages 1.05 and 0.95 to an energy mean of 1.0000, giving 0.97 — tier `B`.

Certification, a quality-inspector action, moves the unit `GATED → CERTIFIED`. It requires `quality_status` to be `GATED`, the model variant to still be `RELEASED` (otherwise `ERR_MODEL_NOT_RELEASED`), and at least one `RECORDED` `ENERGY` test and at least one `RECORDED` `WATER` test to exist — a unit with only one of the two is refused with `ERR_INVALID_STATE`. Finally, the certification-variant index must be at most 1.00; an index above that is refused with `ERR_EFFICIENCY_LIMIT_EXCEEDED` and **nothing** is written, neither `efficiency_index` nor `certification_tier` nor the status. On success, `efficiency_index` and `certification_tier` are both written from the certification variant. The tests of a unit can be listed and filtered by `test_type`, `status` and `result`.

### 3.8. Engineering Change, Part Cut-In and the Service-Supply Obligation

An engineering change is authored by an engineering lead, who supplies the `model_variant_id` whose bill of materials is being changed, the `bom_position_code` being cut in, the `affected_part_id` being replaced, the `target_line_id` on which the cut-in will happen, and the `cut_in_sequence_index` (at least 1) naming the first build-slot sequence index the new bill-of-materials line applies to. Two fields may be supplied now or deferred: `replacement_part_id`, the incoming part, and `new_qty_per_unit`, which must be strictly greater than zero when supplied and which, when the cut-in request itself does not carry one, causes the superseded line's `qty_per_unit` to be inherited. A new change arrives with `status` `DRAFT`, an `origin` of `MANUAL`, a `revision_round` of 0, and null `submitted_by_user_id`, `decided_by_user_id`, `cut_in_at` and `source_warranty_return_id`.

The `origin` field has one other value. A change with `origin` `WARRANTY` is minted only by the field-failure cascade of §3.9, never by a client, and carries a `source_warranty_return_id` pointing at the return that raised it.

The review cycle is deliberately loop-shaped. Submitting takes the change `DRAFT → SUBMITTED`, or `REVISION_REQUESTED → SUBMITTED` on a second pass; either way `submitted_by_user_id` is set to the submitting `X-User-ID`, last submit winning, so a new submitter resets who is allowed to decide. Submission also moves the affected part `ACTIVE → CHANGE_PENDING`, and a `CHANGE_PENDING` part immediately blocks the sequencing of every variant whose effective bill of materials contains it, with `ERR_PART_CHANGE_PENDING`. Starting review takes `SUBMITTED → UNDER_REVIEW`.

Deciding is where segregation of duties bites. The decision request carries a `decision` of `APPROVE`, `REJECT` or `REQUEST_REVISION` and an optional `note`, requires the change to be `UNDER_REVIEW`, and requires the deciding `X-User-ID` to differ from the change's `submitted_by_user_id`; a submitter attempting to decide their own change is refused with `ERR_SEGREGATION_OF_DUTIES`. Whichever branch is taken records `decided_by_user_id` as the deciding `X-User-ID`.

- `APPROVE` moves the change `UNDER_REVIEW → APPROVED`. Nothing else changes; the affected part stays `CHANGE_PENDING`.
- `REJECT` moves it `UNDER_REVIEW → REJECTED` and releases the affected part `CHANGE_PENDING → ACTIVE`, provided no other live change names that part. A change counts as live while its `status` is `SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUESTED` or `APPROVED`.
- `REQUEST_REVISION` normally moves it `UNDER_REVIEW → REVISION_REQUESTED` with `revision_round` incremented by one, and the change re-enters the loop through a fresh submission. The loop is capped at three revision rounds: when the increment would carry `revision_round` beyond 3, the change instead moves `UNDER_REVIEW → CANCELLED`, `revision_round` is nonetheless recorded as 4, the loop is abandoned rather than returning to `REVISION_REQUESTED`, and the affected part returns `CHANGE_PENDING → ACTIVE` when no other live change names it.

**Cutting in** an `APPROVED` change is the depth-four cascade of §2.11. The request may override `replacement_part_id` and `new_qty_per_unit`, and the two behave differently. An omitted `replacement_part_id` falls back to the value stored on the change, and a supplied one is both used and written onto the change. `new_qty_per_unit`, by contrast, is read from the request alone: when the request omits it the superseded line's `qty_per_unit` is inherited even if the change itself carries a `new_qty_per_unit`, and the change's own stored value is left as it stood. Beyond requiring `APPROVED`, the checks run in ladder order: the model variant must be `RELEASED`; an `ACTIVE` bill-of-materials line must exist for the change's `model_variant_id` and `bom_position_code` carrying the `affected_part_id`, failing with `ERR_BOM_NOT_EFFECTIVE`, and where several such lines exist the one superseded is the one with the greatest `effective_from_sequence`, then the latest `created_at`, then the greatest `id`; the target line's `posture` must be `STOPPED`, failing with `ERR_LINE_NOT_STOPPED`, which is why a cut-in is always preceded by a deliberate line stoppage; the `cut_in_sequence_index` must be strictly greater than the target line's `max_released_sequence_index`, failing with `ERR_CUT_IN_INDEX_TOO_LOW`, because a change may not rewrite the bill of materials of appliances already released; and the effective `replacement_part_id` must be non-null and must differ from `affected_part_id`, failing with `ERR_REPLACEMENT_PART_REQUIRED`.

A successful cut-in moves the change `APPROVED → CUT_IN`, stamps `cut_in_at` with the logical clock, and then runs four linked effects:

1. A new bill-of-materials line is minted, with its `part_id` set to the replacement part, its `station_id` and its `qty_per_unit` inherited from the superseded line unless the cut-in request supplied `new_qty_per_unit`, its `effective_from_sequence` set to `cut_in_sequence_index`, its `created_by_change_id` set to this change and its `status` `ACTIVE`. The old line becomes `SUPERSEDED` with `superseded_by_bom_line_id` pointing at the new one.
2. The outgoing part becomes service-only, moving `CHANGE_PENDING → SERVICE_ONLY` in the ordinary case and `ACTIVE → SERVICE_ONLY` when the part was never marked pending, for instance because the change was authored against a different position; its `service_obligation_until` is set to `cut_in_at` plus ten years.
3. Every delivery call for that outgoing part whose `status` is `SCHEDULED` and whose `window_start` falls at or after `cut_in_at` is cancelled with `cancel_reason` `PART_SERVICE_ONLY`.
4. Every build slot pinned to one of those cancelled calls and still `SEQUENCED` is un-sequenced to `PLANNED`, releasing its presentation slots, recomputing its shift plan's labour figures and re-deriving the line's `posture`.

The cut-in is not the end of the change's life. A `CUT_IN` change targeting a line moves `CUT_IN → CLOSED` during that line's next checkpoint sweep, once no production unit built on that same line — that is, whose build slot's `line_id` is the change's `target_line_id` — with a `built_at_sequence_index` strictly below the change's `cut_in_sequence_index` remains in `IN_STATION` or `REWORK` — in other words, once the last pre-change appliance has either finished assembly or shipped. Closing archives the change; the minted bill-of-materials line stays `ACTIVE`.

The **service-part supply obligation** is what keeps legacy parts alive. A part that has become `SERVICE_ONLY` continues to be produced for the service network and may not be retired early: making it obsolete requires the logical clock to be **strictly** past its `service_obligation_until`, and an attempt at exactly that instant is still inside the obligation and refused with `ERR_SERVICE_OBLIGATION_ACTIVE`. Attempting to obsolete a part that is still `ACTIVE` or `CHANGE_PENDING` is refused with `ERR_INVALID_STATE`, since only the `SERVICE_ONLY → OBSOLETE` transition exists. Once the part is `OBSOLETE`, legacy service production ends and the part can no longer appear on a newly authored bill-of-materials line.

Two further part transitions are driven entirely by the system. A part sitting in `CHANGE_PENDING` returns `CHANGE_PENDING → ACTIVE` as soon as the change that named it is `CANCELLED` or `REJECTED` and no other change naming it remains live, and sequencing is unblocked at that moment. Engineering changes can be listed and filtered by `model_variant_id`, `affected_part_id`, `replacement_part_id`, `target_line_id`, `source_warranty_return_id`, `origin` and `status`, and a single-change read exposes `revision_round`, `submitted_by_user_id`, `decided_by_user_id` and `cut_in_at`.

### 3.9. Closing the Loop: Field Failures, Design Feedback and the Overdue Sweep

Field failures come back to the plant as **warranty returns**, filed by a warranty analyst against a shipped appliance. The intake request carries the `production_unit_id` of the returned appliance — which must be a unit whose `assembly_status` is `SHIPPED` — a `failure_code` reported from the service network, the non-negative `field_hours` the appliance accumulated in the field before failing, and optionally a `returned_at` instant recording when the unit reached the teardown bench; when `returned_at` is omitted it defaults to the logical clock. The return arrives with `status` `RECEIVED` and with null `teardown_started_at`, `disposition`, `root_cause_part_id`, `engineering_change_id` and `design_feedback_note`.

Teardown takes the return `RECEIVED → TEARDOWN` and stamps `teardown_started_at` with the logical clock. Analysis then branches on a supplied `disposition`, and the three branches diverge sharply in what they touch.

The two defect branches both require a `root_cause_part_id`, whose absence is a schema violation rejected with `ERR_INVALID_REQUEST` before the return is even resolved, and that part must appear on the returned appliance's **as-built** bill of materials, resolved at the unit's `built_at_sequence_index` — the flavour that admits `SUPERSEDED` lines, so a part cut out of production remains a legitimate root cause for an appliance built before the cut-in. A root cause absent from that resolution is refused with `ERR_BOM_NOT_EFFECTIVE`.

- A `disposition` of `DESIGN_DEFECT` takes the return `TEARDOWN → ANALYZED_DESIGN`. The root-cause part's `field_failure_count` is incremented by one and its `cohort_failure_rate_per_1000` is recomputed. If that recomputed cohort rate is greater than or equal to 8.00, the design-feedback cascade fires: a `WARRANTY`-origin engineering change is minted directly in `SUBMITTED`, with its `model_variant_id` and `bom_position_code` taken from the unit's as-built bill of materials — the alphabetically first `bom_position_code` whose resolved line names the root-cause part, should the part sit at more than one position — its `affected_part_id` set to the root-cause part, its `replacement_part_id` left null for an engineer to fill in later, its `target_line_id` set to the line the unit was built on, its `cut_in_sequence_index` set to that line's `max_released_sequence_index` plus one, and its `submitted_by_user_id` recorded as the literal value `system`. The change's `source_warranty_return_id` points back at the return, and the return's `engineering_change_id` points at the change. Because that change is already `SUBMITTED`, it moves the root-cause part `ACTIVE → CHANGE_PENDING`, which in turn blocks further sequencing of every variant whose effective bill of materials contains that part.
- A `disposition` of `SUPPLIER_DEFECT` takes the return `TEARDOWN → ANALYZED_SUPPLIER`. The part's `field_failure_count` and `cohort_failure_rate_per_1000` move exactly as in the design branch, and additionally the part's supplier is charged: its `quality_penalty_count` is incremented by one, 10 points are subtracted from its `on_time_score` with a floor of 0.00, and its `status` is re-derived — with the same demotion cascade a missed delivery would trigger, cancelling that supplier's remaining `SCHEDULED` calls and un-sequencing their dependent slots. Crucially, **no** engineering change is minted on this branch and `engineering_change_id` stays null; that is the whole divergence from the design branch.
- A `disposition` of `NO_FAULT_FOUND` requires that no `root_cause_part_id` be supplied — supplying one is the same schema violation, `ERR_INVALID_REQUEST` — and takes the return straight `TEARDOWN → CLOSED`. No counter moves, no change is minted, and the return needs no separate closure.

Closing an analysed return takes it `ANALYZED_DESIGN → CLOSED` or `ANALYZED_SUPPLIER → CLOSED` and stores the optional `design_feedback_note` filed by the analyst. All analysis side effects stand; no counter is unwound.

Withdrawing an analysed return also takes it `ANALYZED_DESIGN → CLOSED` or `ANALYZED_SUPPLIER → CLOSED`, may carry an explanatory `reason`, and undoes the attribution instead of confirming it. Its `disposition` is rewritten to `NO_FAULT_FOUND` while `root_cause_part_id` is deliberately kept for audit. The charged part's `field_failure_count` is decremented by one and its `cohort_failure_rate_per_1000` recomputed. When the return had been attributed to a supplier, that supplier's `quality_penalty_count` is decremented by one, 10 points are added back to its `on_time_score` capped at 100.00, and its `status` is re-derived. And when the return's `engineering_change_id` points at a `WARRANTY`-origin change that has not yet been decided, that change is cancelled — `DRAFT → CANCELLED`, `SUBMITTED → CANCELLED` or `UNDER_REVIEW → CANCELLED`, according to the `status` it was in — and the affected part returns `CHANGE_PENDING → ACTIVE`.

**Field-failure intensity** for a part is reported by a dedicated warranty-metrics read available to plant administrators, engineering leads and warranty analysts. The numerator is shared by both variants: the number of warranty returns whose `status` is `ANALYZED_DESIGN`, `ANALYZED_SUPPLIER` or `CLOSED`, whose `root_cause_part_id` is the part in question, and whose `disposition` is `DESIGN_DEFECT` or `SUPPLIER_DEFECT` — which is exactly why a withdrawn return, rewritten to `NO_FAULT_FOUND`, silently leaves the numerator. The **production-cohort** rate is one thousand multiplied by that failure count, divided by the cohort size, rounded to two decimal places; the cohort size counts every production unit whose as-built bill of materials contains the part and whose `assembly_status` is `SHIPPED`. This is the variant stored on the part's `cohort_failure_rate_per_1000` and the only one compared against the 8.00 auto-change trigger. The **shipped-exposure** rate is one thousand multiplied by the two thousand hours a unit is expected to run in a year, multiplied by the failure count, divided by the total field hours — the sum of `field_hours` over the counted returns — and rounded to two decimal places; it is reported only, normalising for how long the appliances were actually in service. A zero denominator in either variant yields 0.00 and never triggers anything. Two shipped cohort units carrying a part with one design-defect return of 500 field hours illustrate the divergence: the production-cohort rate is 500.00 while the shipped-exposure rate is 4000.00. The metrics response reports `part_id`, `failure_count`, `cohort_units`, `total_field_hours`, `cohort_failure_rate_per_1000`, `shipped_exposure_rate_per_1000`, `trigger_threshold` — which is 8.00 — and `trigger_breached`, a boolean reflecting the production-cohort variant alone.

Warranty returns can be listed and filtered by `production_unit_id`, `root_cause_part_id`, `engineering_change_id`, `disposition` and `status`.

**The checkpoint sweep** is the deterministic housekeeping pass a production planner or plant administrator runs on one line to settle everything the logical clock has made overdue. Its five steps run in exactly this order, and nothing outside them happens:

1. The line's `checkpoint_index` is incremented by one.
2. Every delivery call whose `status` is `SCHEDULED`, whose `station_id` belongs to this line, and whose `window_end` plus the fifteen-minute miss grace period is at or before the logical clock moves `SCHEDULED → MISSED`. These are processed in ascending `window_end` and then ascending `created_at` order. Each one increments its supplier's `missed_count` and subtracts 20 points from its `on_time_score` with a floor of 0.00, then re-derives the supplier's `status`; a supplier demoted out of `APPROVED` has every one of its remaining `SCHEDULED` calls outside this checkpoint's overdue set — the set the sweep selected at the head of this step, whether a given member has already been marked `MISSED` or is still waiting its turn — cancelled with `cancel_reason` `SUPPLIER_PROBATION`, and every build slot pinned to one of those cancellations and still `SEQUENCED` is un-sequenced to `PLANNED` with the full reversal.
3. Every build slot on the line still `PLANNED` whose `planned_start` is earlier than the logical clock becomes `CANCELLED`, freeing its `sequence_index`.
4. Every `CUT_IN` engineering change whose `target_line_id` is this line, and all of whose pre-cut-in units have left `IN_STATION` and `REWORK`, becomes `CLOSED`.
5. The line's `posture`, `free_slot_pct` and `max_released_sequence_index` are recomputed.

The sweep reports what it did, returning the new `checkpoint_index` together with the identifier lists `missed_call_ids`, `cancelled_call_ids`, `de_sequenced_build_slot_ids`, `cancelled_build_slot_ids`, `demoted_supplier_ids` and `closed_change_ids`.

## 4. Endpoint Definitions

All endpoints are mounted at the root of the API. Operations that create a new resource — a line, a station, a model variant, a supplier, a part, a bill-of-materials line, a delivery call, a shift plan, a build slot, a quality test, an engineering change or a warranty return — return `201 Created`, as does releasing a build slot, which mints a production unit. Every other mutating operation, including every state transition, the checkpoint sweep and the logical-clock setter, returns `200 OK`, as do all reads. In the table below, **All six plant-internal roles** means `PlantAdmin`, `ProductionPlanner`, `LineOperator`, `QualityInspector`, `EngineeringLead` and `WarrantyAnalyst`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock used by every temporal rule | All six plant-internal roles |
| POST | `/lines` | Create an assembly line | PlantAdmin |
| GET | `/lines/{id}` | Read a line, including derived posture and version | All six plant-internal roles |
| POST | `/lines/{id}/stop` | Stop the line and record a reason | LineOperator, PlantAdmin |
| POST | `/lines/{id}/start` | Start the line, optionally performing a family changeover | LineOperator, PlantAdmin |
| POST | `/lines/{id}/run-checkpoint` | Run the deterministic overdue sweep on one line | ProductionPlanner, PlantAdmin |
| POST | `/stations` | Create a station on a line | PlantAdmin |
| GET | `/stations/{id}` | Read one station, including committed presentation slots | PlantAdmin, ProductionPlanner, LineOperator, QualityInspector, EngineeringLead |
| GET | `/lines/{id}/stations` | List the stations of one line in flow order | PlantAdmin, ProductionPlanner, LineOperator, QualityInspector, EngineeringLead |
| POST | `/model-variants` | Create a model variant with its test limits | PlantAdmin |
| GET | `/model-variants/{id}` | Read a model variant, including its version | All six plant-internal roles |
| POST | `/model-variants/{id}/release` | Release a draft model variant for production | PlantAdmin |
| POST | `/model-variants/{id}/obsolete` | Obsolete a released model variant | PlantAdmin |
| POST | `/suppliers` | Register a supplier | PlantAdmin |
| GET | `/suppliers/{id}` | Read supplier scoring state | PlantAdmin, ProductionPlanner, QualityInspector, EngineeringLead, WarrantyAnalyst, SupplierPortal |
| POST | `/parts` | Register a part | PlantAdmin |
| GET | `/parts/{id}` | Read part lifecycle state and service obligation | All six plant-internal roles |
| GET | `/parts` | List parts with filters | PlantAdmin, ProductionPlanner, EngineeringLead, WarrantyAnalyst, SupplierPortal |
| POST | `/parts/{id}/obsolete` | Obsolete a service-only part after its obligation elapses | PlantAdmin |
| GET | `/parts/{id}/warranty-metrics` | Read both field-failure rate variants for a part | PlantAdmin, EngineeringLead, WarrantyAnalyst |
| POST | `/bom-lines` | Author a bill-of-materials line (version-guarded) | PlantAdmin, EngineeringLead |
| GET | `/bom-lines/{id}` | Read one bill-of-materials line | All six plant-internal roles |
| GET | `/bom-lines` | List bill-of-materials lines with filters and sequence resolution | All six plant-internal roles |
| POST | `/delivery-calls` | Book a synchronous delivery call at a station dock | ProductionPlanner, PlantAdmin |
| GET | `/delivery-calls/{id}` | Read one delivery call, including lateness | PlantAdmin, ProductionPlanner, LineOperator, EngineeringLead, SupplierPortal |
| GET | `/delivery-calls` | List delivery calls with filters | PlantAdmin, ProductionPlanner, LineOperator, EngineeringLead, SupplierPortal |
| POST | `/delivery-calls/{id}/record-arrival` | Record arrival against a scheduled call | SupplierPortal |
| POST | `/delivery-calls/{id}/cancel` | Cancel a scheduled call by planner decision | ProductionPlanner, PlantAdmin |
| POST | `/shift-plans` | Create a shift plan (version-guarded, may supersede) | ProductionPlanner, PlantAdmin |
| GET | `/shift-plans/{id}` | Read one shift plan and its labour figures | PlantAdmin, ProductionPlanner, LineOperator, EngineeringLead |
| GET | `/lines/{id}/shift-plans` | List the shift plans of one line | PlantAdmin, ProductionPlanner, LineOperator, EngineeringLead |
| POST | `/build-slots` | Create a planned build slot at a sequence position | ProductionPlanner, PlantAdmin |
| GET | `/build-slots/{id}` | Read one build slot and its pinned allocations | PlantAdmin, ProductionPlanner, LineOperator, QualityInspector, EngineeringLead |
| GET | `/build-slots` | List build slots with filters | PlantAdmin, ProductionPlanner, LineOperator, QualityInspector, EngineeringLead |
| POST | `/build-slots/{id}/sequence` | Sequence a planned slot, committing capacity | ProductionPlanner |
| POST | `/build-slots/{id}/de-sequence` | Un-sequence a slot, reversing every charge | ProductionPlanner |
| POST | `/build-slots/{id}/release` | Release a sequenced slot and mint a production unit | LineOperator |
| GET | `/production-units/{id}` | Read a unit's two status dimensions and efficiency figures | All six plant-internal roles |
| GET | `/production-units` | List production units with filters | All six plant-internal roles |
| POST | `/production-units/{id}/quality-tests` | Record a quality measurement against a unit | QualityInspector |
| GET | `/production-units/{id}/quality-tests` | List the quality tests of one unit | PlantAdmin, QualityInspector, EngineeringLead, WarrantyAnalyst |
| POST | `/production-units/{id}/clear-quarantine` | Void failing tests and reopen a quarantined unit | QualityInspector |
| POST | `/production-units/{id}/certify` | Certify a gated unit's efficiency index and tier | QualityInspector |
| POST | `/production-units/{id}/complete-assembly` | Complete assembly of a unit | LineOperator |
| POST | `/production-units/{id}/ship` | Ship a certified unit and release its presentation slots | LineOperator |
| POST | `/engineering-changes` | Author a draft engineering change | EngineeringLead |
| GET | `/engineering-changes/{id}` | Read one engineering change and its review state | PlantAdmin, ProductionPlanner, EngineeringLead, WarrantyAnalyst, QualityInspector |
| GET | `/engineering-changes` | List engineering changes with filters | PlantAdmin, ProductionPlanner, EngineeringLead, WarrantyAnalyst, QualityInspector |
| POST | `/engineering-changes/{id}/submit` | Submit a change for review | EngineeringLead |
| POST | `/engineering-changes/{id}/start-review` | Begin review of a submitted change | EngineeringLead |
| POST | `/engineering-changes/{id}/decide` | Approve, reject or request revision of a change | EngineeringLead |
| POST | `/engineering-changes/{id}/cut-in` | Cut the change into production on a stopped line | EngineeringLead |
| POST | `/warranty-returns` | File a warranty return against a shipped unit | WarrantyAnalyst |
| GET | `/warranty-returns/{id}` | Read one warranty return | PlantAdmin, EngineeringLead, WarrantyAnalyst, QualityInspector |
| GET | `/warranty-returns` | List warranty returns with filters | PlantAdmin, EngineeringLead, WarrantyAnalyst, QualityInspector |
| POST | `/warranty-returns/{id}/teardown` | Begin teardown of a received return | WarrantyAnalyst |
| POST | `/warranty-returns/{id}/analyze` | Record a disposition and root cause | WarrantyAnalyst |
| POST | `/warranty-returns/{id}/close` | Close an analysed return with design feedback | WarrantyAnalyst |
| POST | `/warranty-returns/{id}/withdraw` | Withdraw an analysed return, reversing attribution | WarrantyAnalyst |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_ROLE_NOT_PERMITTED` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_SUPPLIER_SCOPE_VIOLATION` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_STALE_MODEL_VARIANT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_LINE_VERSION` | 412 Precondition Failed |
| `ERR_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_STATION_NOT_FOUND` | 404 Not Found |
| `ERR_MODEL_VARIANT_NOT_FOUND` | 404 Not Found |
| `ERR_SUPPLIER_NOT_FOUND` | 404 Not Found |
| `ERR_PART_NOT_FOUND` | 404 Not Found |
| `ERR_BOM_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_DELIVERY_CALL_NOT_FOUND` | 404 Not Found |
| `ERR_SHIFT_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_BUILD_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCTION_UNIT_NOT_FOUND` | 404 Not Found |
| `ERR_ENGINEERING_CHANGE_NOT_FOUND` | 404 Not Found |
| `ERR_WARRANTY_RETURN_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_DUPLICATE_CODE` | 409 Conflict |
| `ERR_TEST_NOT_APPLICABLE` | 422 Unprocessable Entity |
| `ERR_QUALITY_GATE_ORDER` | 409 Conflict |
| `ERR_UNIT_QUARANTINED` | 409 Conflict |
| `ERR_EFFICIENCY_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_MODEL_NOT_RELEASED` | 409 Conflict |
| `ERR_BOM_NOT_EFFECTIVE` | 422 Unprocessable Entity |
| `ERR_PART_CHANGE_PENDING` | 409 Conflict |
| `ERR_LINE_NOT_STOPPED` | 409 Conflict |
| `ERR_CUT_IN_INDEX_TOO_LOW` | 422 Unprocessable Entity |
| `ERR_REPLACEMENT_PART_REQUIRED` | 422 Unprocessable Entity |
| `ERR_SERVICE_OBLIGATION_ACTIVE` | 409 Conflict |
| `ERR_CHANGEOVER_REQUIRED` | 409 Conflict |
| `ERR_DOCK_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_SHIFT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_NO_SHIFT_COVERAGE` | 422 Unprocessable Entity |
| `ERR_SEQUENCE_INDEX_TAKEN` | 409 Conflict |
| `ERR_LINE_POSTURE_BLOCKED` | 409 Conflict |
| `ERR_SUPPLIER_NOT_APPROVED` | 409 Conflict |
| `ERR_SYNC_DELIVERY_MISSING` | 422 Unprocessable Entity |
| `ERR_OPTION_LOAD_WINDOW_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PRESENTATION_SLOTS_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_LABOR_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
