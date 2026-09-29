# Pump Manufacturing & Hydraulic Testing API — Product Requirements Document

## 1. Introduction

An industrial centrifugal pump is not a catalogue item; it is a promise. A customer arrives with a duty point — so many cubic metres per hour against so many metres of head, in a fluid that may be hot, salty, viscous or full of sand — and the manufacturer answers with a machine whose impeller has been trimmed to a specific diameter, whose casing and impeller are poured in a specific alloy at a specific foundry, whose seal is piped to a specific API 682 flush plan, and whose head-flow curve has been measured on a test bed and certified against an ISO 9906 acceptance grade. Every one of those decisions is auditable, and every one of them is a place where liability can later attach. This API is the system of record that keeps the promise and the machine aligned from first enquiry to warranty settlement.

The business problem it solves is traceability under divergence. Hydraulic sizing is predictive: the application engineer computes what the trimmed impeller *should* deliver. Performance testing is empirical: the test engineer measures what the assembled machine *actually* delivers, sometimes at a speed other than nameplate, and must decide whether to report the raw measurement or correct it to rated speed by the affinity laws. Field troubleshooting is forensic: two years later a customer complains of low head, and someone must determine whether the machine underperforms its guarantee or whether the installation is starving it of suction pressure, running it above rated speed, or feeding it more solids than the seal configuration was ever rated for. The three views of the same pump routinely disagree, and the system must record exactly which one the warranty was written against.

Alongside that hydraulic spine runs a physical-asset spine: casting patterns that wear out and must be refurbished, foundries with finite concurrent pour capacity and a limited list of approved alloys, casting lots whose pieces are scrapped, weld-repaired and re-accepted, build orders that go short of castings and must be re-bound, and spare-parts kits that must remain interchangeable across design generations long after the original model is superseded. Interference between the two spines is the norm rather than the exception — a scrapped casting can strand a build order, hold a fully engineered skid and release its reserved spare-parts kits, all inside a single request — and the specification below is explicit about every one of those propagations because getting them silently wrong is what destroys an audit trail.

## 2. Global Specifications & System-Wide Principles

The whole API is mounted at the server root; resource collections such as `/selections` and `/casting-lots` sit directly beneath it. This section fixes the rules that hold everywhere: identity, envelope shape, paging, audit fields, arithmetic precision, rejection ordering, concurrency tokens, and the cross-entity propagation contracts.

### 2.1. User and Role-Based Access Control

Every request, without exception, carries two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which that principal acts. If either header is absent or empty, or if `X-User-Role` is not one of the eight role names below, the request is rejected with `ERR_UNAUTHENTICATED` and HTTP 401. If the headers are well formed but the declared role is not among the roles authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` and HTTP 403.

The eight roles are `PlatformAdmin`, `ApplicationEngineer`, `HydraulicApprover`, `FoundryPartner`, `QualityInspector`, `TestEngineer`, `ProductionPlanner`, and `WarrantyAdjudicator`. Their responsibilities partition the manufacturing chain along segregation-of-duties lines. `PlatformAdmin` is the master-data custodian, owning foundries, hydraulic models, casting tooling, material and seal configurations, the spare-parts catalogue, and the logical clock. `ApplicationEngineer` owns customer enquiries, hydraulic sizing, and the raising of field claims. `HydraulicApprover` is the independent approver of hydraulic selections and may never approve a selection they themselves proposed. `FoundryPartner` is the external casting supplier. `QualityInspector` inspects, accepts, quarantines and dispositions castings. `TestEngineer` runs the performance test, freezes the measured point set, evaluates both result dimensions and issues the certified curve. `ProductionPlanner` plans builds, records assembly measurements, moves spare-parts stock, and engineers, releases and ships packages. `WarrantyAdjudicator` adjudicates and settles warranty claims and may never adjudicate a claim they submitted. Every role, including every one of the eight, may call every read endpoint in the API.

Identity resolution differs by role, and the difference matters for scoping. When `X-User-Role` is `FoundryPartner`, `X-User-ID` is the `id` of the acting `Foundry`; ownership checks on any resource that references a `Foundry` compare the resource's foundry reference to `X-User-ID`. Concretely, when a foundry partner records a pour, the `foundry_id` supplied in the request body must equal the caller's `X-User-ID`, and a mismatch is rejected with `ERR_FOUNDRY_SCOPE_VIOLATION` and HTTP 403. For the other seven roles — `PlatformAdmin`, `ApplicationEngineer`, `HydraulicApprover`, `QualityInspector`, `TestEngineer`, `ProductionPlanner` and `WarrantyAdjudicator` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it wherever a transition captures an actor (as `proposed_by_user_id` and `approved_by_user_id` on a selection, as `reported_by_user_id` and `dispositioned_by_user_id` on a casting defect, and as `submitted_by_user_id` and `adjudicated_by_user_id` on a warranty claim) but never compares it to any entity's `id`.

Three segregation-of-duties comparisons are built on those captured identifiers, and all three compare the acting `X-User-ID` against a stored value rather than against a role. Selection approval requires that the approver differ from the recorded proposer, and a match yields `ERR_SEGREGATION_OF_DUTIES`. A `USE_AS_IS` casting disposition requires that the dispositioning inspector differ from the inspector who reported the defect, and a match likewise yields `ERR_SEGREGATION_OF_DUTIES`. Warranty adjudication requires that the adjudicator differ from the claim submitter, and a match yields `ERR_ADJUDICATOR_CONFLICT`.

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

Collection endpoints accept two query parameters. `limit` caps the number of rows returned; when omitted it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100. `offset` is the number of rows to skip before the first returned row; when omitted it defaults to 0, and its minimum accepted value is 0.

Unless a collection endpoint states otherwise, rows are returned sorted by `created_at` in ascending order.

Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope. `total_count` is the number of rows matching the filters before paging is applied; `has_more` is true when rows matching the filters remain beyond the current window.

Beyond paging, most collections accept narrowing filters, all of them exact-match. Foundries, enquiries, casting defects, casting lots, patterns, models, selections, build orders, packages, repair kits, allocations and claims may all be filtered by `status`; performance tests are filtered instead by `run_state`, `hydraulic_status` or `npsh_status`, matching their three independent result dimensions. Patterns and repair kits may be filtered by `pump_model_id`; patterns and casting lots by `foundry_id`; models and repair kits by `interchange_group`; models additionally by `superseded_by_model_id`, which resolves the self-referential successor link in reverse and so answers "what did this model replace"; configurations by `pump_model_id` or `service_class`; selections by `duty_application_id`, `pump_model_id` or `material_seal_config_id`; casting lots by `pattern_asset_id`; casting defects by `casting_lot_id`; build orders by `selection_id` or `casting_lot_id`; performance tests by `build_order_id`; measured points by `test_run_id`; packages by `build_order_id` or `test_run_id`; allocations by `repair_kit_id` or `build_order_id`; and warranty claims by `pump_package_id`.

### 2.4. Common Resource Properties and the Logical Clock

Every resource carries a server-minted `id`, formatted as a UUID with no type prefix, and a `created_at` timestamp rendered as an ISO 8601 UTC instant with three fractional digits. Most resources additionally carry `updated_at`, an ISO 8601 UTC instant refreshed on every mutation, and `version`, an integer that begins at 1 when the resource is created and increments by exactly 1 on every mutation of that resource — including mutations the client did not ask for directly, such as a derived counter being reconciled or a cascade repositioning a parent.

Two entity types are immutable after creation and therefore carry only `id` and `created_at`: a material and seal configuration, and an individual measured test point. Neither has an `updated_at` field and neither has a `version` field; the fields are absent from their representations rather than present and null. Everything else — foundries, hydraulic models, casting patterns, enquiries, selections, casting lots, casting defects, build orders, performance test runs, engineered packages, repair kits, kit allocations and warranty claims — carries the full set of four.

All time-dependent behaviour reads a server-managed **logical clock** rather than wall-clock time. Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time. A `PlatformAdmin` may move it by supplying a `to_iso8601` instant to the clock-setting endpoint, which responds with the resulting `current_utc` value and mutates no entity; any role may read the current value from the clock-reading endpoint, which likewise responds with `current_utc`. Spare-parts support windows, warranty age and every other date comparison in this specification are evaluated against this clock.

### 2.5. Numeric Precision and Rounding

Rounding in this domain is not cosmetic — a value rounded at the wrong step propagates into a different acceptance verdict — so the evaluation order stated for each calculation in §3 is binding, and intermediate values are only rounded where the text explicitly says so.

Unless stated otherwise, every stored numeric result is rounded to two decimal places using the round-half-up convention (a value exactly at the midpoint rounds away from zero). Three results depart from that default. A trimmed impeller diameter is rounded to **one** decimal place, half up, because impellers are machined to a tenth of a millimetre. A stored speed ratio is rounded to **four** decimal places, half up. And every quantity ledger — castings poured, scrapped, held in rework and accepted; kit units received, on hand, reserved, issued and consumed; pattern pour counters and wear indices; rework and refurbishment cycle counts — is pure integer arithmetic with no rounding at all.

Ratios and penalty terms that feed a later step are held unrounded unless the calculation names them as stored fields. Where a percentage tier or a multiplicative factor is selected from a table, the selected value is an exact constant and is not rounded.

### 2.6. Rejection Precedence

When a request violates more than one rule, exactly one error is returned, and which one is fully determined: checks are evaluated in the fixed global order below, and the first violated check ends the request. The order is a single ladder shared by the whole API; an endpoint simply skips the rungs that do not apply to it. Text order elsewhere in this document does not imply evaluation order — this list does.

1. Authentication: both headers present and `X-User-Role` one of the eight declared roles — `ERR_UNAUTHENTICATED`.
2. Authorisation: the acting role appears in the called endpoint's authorised roles — `ERR_UNAUTHORIZED`.
3. Request shape: every required input field present, no unknown fields, correct types, enum members valid, and the numeric constraints attached to entity fields respected — `ERR_INVALID_REQUEST`. One deliberate exception: the strictly-positive lower bounds of `requested_qty`, `qty_poured`, `affected_qty` and `qty` are *not* enforced here but at rungs 12 and 13, so that a zero quantity surfaces as `ERR_ZERO_QUANTITY` rather than being masked as a malformed request.
4. Path existence: every resource addressed by a path segment exists, validated left to right along the path — `ERR_NOT_FOUND`. On a nested path the outer identifier is resolved before the inner one, so a request naming a non-existent parent fails on the parent.
5. Body reference existence: every foreign key supplied in the request body resolves to an existing row, validated in the order the fields are declared in the endpoint's input list — `ERR_REFERENCED_RESOURCE_NOT_FOUND`.
6. Foundry scoping on a pour: `ERR_FOUNDRY_SCOPE_VIOLATION`.
7. Selection approval segregation of duties: `ERR_SEGREGATION_OF_DUTIES`.
8. `USE_AS_IS` disposition segregation of duties: `ERR_SEGREGATION_OF_DUTIES`.
9. Warranty adjudication conflict: `ERR_ADJUDICATOR_CONFLICT`.
10. Enquiry concurrency token: `ERR_STALE_DUTY_APPLICATION_VERSION`.
11. Repair-kit concurrency token: `ERR_STALE_REPAIR_KIT_VERSION`.
12. `requested_qty` at least 1: `ERR_ZERO_QUANTITY`.
13. `qty_poured`, `affected_qty` and `qty` each at least 1: `ERR_ZERO_QUANTITY`.
14. Uniqueness of the supplied code: `ERR_DUPLICATE_CODE`.
15. Defect quantity against the lot ledger: `ERR_AFFECTED_QTY_EXCEEDS_LEDGER`.
16. Enquiry openness for sizing: `ERR_DUTY_APPLICATION_NOT_OPEN`.
17. Per-entity state-machine admissibility, in this order of entities: selection (`ERR_SELECTION_INVALID_STATE`), casting lot (`ERR_CASTING_LOT_INVALID_STATE`), casting defect (`ERR_DEFECT_INVALID_STATE`), build order (`ERR_BUILD_ORDER_INVALID_STATE`), performance test run (`ERR_TEST_RUN_INVALID_STATE`), package (`ERR_PACKAGE_INVALID_STATE`), kit allocation (`ERR_ALLOCATION_INVALID_STATE`), warranty claim (`ERR_CLAIM_INVALID_STATE`), casting pattern (`ERR_PATTERN_INVALID_STATE`).
18. Repair kit still catalogued: `ERR_REPAIR_KIT_DISCONTINUED`.
19. Foundry not suspended: `ERR_FOUNDRY_SUSPENDED`.
20. Model orderability: `ERR_MODEL_NOT_ORDERABLE`.
21. A qualified pattern exists for the model: `ERR_PATTERN_NOT_QUALIFIED`.
22. Casting lot accepted: `ERR_CASTING_LOT_NOT_ACCEPTED`.
23. Test run certified: `ERR_TEST_RUN_NOT_CERTIFIED`.
24. Selection approved: `ERR_SELECTION_NOT_APPROVED`.
25. Build order assembled: `ERR_BUILD_ORDER_NOT_ASSEMBLED`.
26. Build order tested: `ERR_BUILD_ORDER_NOT_TESTED`.
27. Package shipped: `ERR_PACKAGE_NOT_SHIPPED`.
28. Configuration belongs to the named model: `ERR_CONFIG_MODEL_MISMATCH`.
29. Casting lot belongs to the selected model: `ERR_LOT_MODEL_MISMATCH`.
30. Alloy approved at the foundry: `ERR_ALLOY_NOT_APPROVED`.
31. Test run belongs to the named build order: `ERR_TEST_RUN_BUILD_MISMATCH`.
32. Successor model is not the model itself: `ERR_SUCCESSOR_MODEL_INVALID`.
33. Kit interchange group matches: `ERR_KIT_GROUP_MISMATCH`.
34. Process temperature within configuration limit: `ERR_TEMPERATURE_LIMIT_EXCEEDED`.
35. Chloride within configuration limit: `ERR_CHLORIDE_LIMIT_EXCEEDED`.
36. Solids within configuration limit: `ERR_SOLIDS_LIMIT_EXCEEDED`.
37. Viscosity within configuration limit: `ERR_VISCOSITY_LIMIT_EXCEEDED`.
38. Service class matches the enquiry requirement: `ERR_SERVICE_CLASS_MISMATCH`.
39. Duty flow within the model's flow envelope: `ERR_DUTY_FLOW_ABOVE_MAX`.
40. Trimmed diameter not below the casing minimum: `ERR_TRIM_BELOW_MINIMUM`.
41. Trimmed diameter not above the full diameter: `ERR_DUTY_POINT_ABOVE_ENVELOPE`.
42. Certified suction margin sufficient: `ERR_NPSH_MARGIN_INSUFFICIENT`.
43. Residual unbalance within allowance: `ERR_UNBALANCE_EXCEEDS_ALLOWANCE`.
44. Running clearance inside the acceptance band: `ERR_CLEARANCE_OUT_OF_BAND`.
45. Installed flush plan matches the configuration: `ERR_FLUSH_PLAN_MISMATCH`.
46. Enough measured points for the grade: `ERR_INSUFFICIENT_TEST_POINTS`.
47. Exactly one designated suction point: `ERR_NPSH_TEST_POINT_MISSING`.
48. Guarantee flow bracketed by the reported curve: `ERR_GUARANTEE_FLOW_NOT_BRACKETED`.
49. Hydraulic dimension within tolerance: `ERR_HYDRAULIC_OUT_OF_TOLERANCE`.
50. Suction dimension verified: `ERR_NPSH_NOT_VERIFIED`.
51. Pattern occupation window free: `ERR_PATTERN_WINDOW_CONFLICT`.
52. Foundry concurrent pour capacity available: `ERR_FOUNDRY_POUR_CAPACITY_EXCEEDED`.
53. Window ordering valid: `ERR_INVALID_WINDOW`.
54. Rework loop budget available: `ERR_REWORK_LIMIT_EXCEEDED`.
55. Kit covers the model generation: `ERR_KIT_GENERATION_NOT_COVERED`.
56. Kit support window open: `ERR_KIT_SUPPORT_WINDOW_EXPIRED`.
57. Kit stock sufficient: `ERR_KIT_STOCK_INSUFFICIENT`.
58. Interchange selector found a candidate: `ERR_NO_INTERCHANGEABLE_KIT`.
59. Warranty period not expired: `ERR_WARRANTY_EXPIRED`.
60. Claim lines present and positive: `ERR_EMPTY_CLAIM_LINES`.
61. No open defects on the lot: `ERR_OPEN_DEFECTS_PRESENT`.
62. At least one acceptable casting: `ERR_NO_ACCEPTABLE_CASTINGS`.
63. Predicted efficiency meets the contractual target: `ERR_EFFICIENCY_TARGET_NOT_MET`.
64. Motor rating sufficient: `ERR_MOTOR_UNDERSIZED`.

Two consequences of this ladder are worth calling out because they are counter-intuitive. The three segregation-of-duties comparisons sit at rungs 7, 8 and 9, *above* the per-entity state checks at rung 17: a `HydraulicApprover` who tries to approve their own proposal receives `ERR_SEGREGATION_OF_DUTIES` even if the selection is in a state from which approval is impossible. And on hydraulic sizing, the computed geometry is produced before the business gates that read it, so the envelope, efficiency and suction rules at rungs 40, 41 and 63 always compare against fully computed values.

### 2.7. Optimistic Concurrency on Enquiries and Kit Stock

Exactly two write endpoints take a concurrency token, and both take it because the parent they attach to legitimately accepts an unbounded number of children — no state precondition would ever stop a second write, so the token is the only mechanism that makes the writer's view of the parent explicit.

A `POST /selections` request must carry `expected_duty_application_version` as a required, non-optional input field, holding the client's last observed `version` of the target `DutyApplication`. An enquiry accepts more than one selection over its life, because it returns to `OPEN` whenever an approved selection is superseded or a build order is sent back for review. If `expected_duty_application_version` does not equal the enquiry's current `version`, the create is rejected with `ERR_STALE_DUTY_APPLICATION_VERSION` and HTTP 412, so a client cannot size a pump against an enquiry state it has not observed. The `version` returned by reading a single enquiry is the token to send.

A `POST /kit-allocations` request must carry `expected_repair_kit_version` as a required, non-optional input field, holding the client's last observed `version` of the named `RepairKit`. Receipts, issues, consumptions and cascaded releases all move that kit's stock counters and bump its `version`. If `expected_repair_kit_version` does not equal the kit's current `version`, the reservation is rejected with `ERR_STALE_REPAIR_KIT_VERSION` and HTTP 412, forcing the writer to re-read the counters before committing stock. The `version` returned by reading a single repair kit is the token to send.

No other endpoint in the API accepts a version field. In particular, the selector-driven allocation endpoint takes no token, because the client does not name the kit and therefore has no kit version to have observed.

### 2.8. Cascade Propagation Across the Manufacturing Chain

The system uses immediate consistency: when a write satisfies the trigger for a downstream repositioning, that repositioning happens inside the same request, and every entity it touches has its `updated_at` refreshed and its `version` incremented by 1. Clients never poll for reconciliation. Three multi-hop cascades run through the chain, and each is specified in full in §3, but their shape is worth stating once here because implementers routinely stop after the first hop.

**The casting-short cascade** starts in the foundry and ends in the spare-parts store. A scrap or weld-repair disposition recomputes the parent lot's piece ledger; if the lot can no longer cover its committed builds it moves to `QUARANTINED`; that in turn strands the newest non-terminal build order bound to the lot, which moves to `CASTING_SHORT`; that in turn puts the build order's non-terminal engineered package on `HELD` and clears its promised ship date; and that in turn releases every still-reserved kit allocation on the same build order, returning their units to stock. Four hops, one request.

**The failed-test cascade** runs upstream instead of downstream. When a performance test's hydraulic dimension is evaluated as out of tolerance, the build order moves to `REWORK_REQUIRED`, which pulls the approved selection back to `UNDER_REVIEW`, which returns the customer enquiry from `CONTRACTED` to `OPEN` so the application engineer can re-size. Three hops.

**The pattern-wear cascade** couples tooling condition to catalogue orderability. A pour, or the first critical defect against a lot poured from a pattern, advances that pattern's wear index; when the index reaches the pattern's withdrawal threshold the pattern moves to `WORN`; and if the model it produces has no other qualified pattern left, the model itself moves from `ORDERABLE` to `PATTERN_CONSTRAINED` and stops accepting new selections. Retiring tooling raises the same second hop. Completing a refurbishment runs it in reverse, returning the pattern to `QUALIFIED` and, when it is the model's only qualified pattern, the model to `ORDERABLE`.

### 2.9. Conserved Quantities

Two integer ledgers in the system are conserved, and the conservation is an invariant that must hold after every transition that touches them — not merely after a happy-path sequence.

For a casting lot, the pieces poured are always fully accounted for: the accepted count plus the count held in weld rework plus the scrapped count equals `qty_poured`. That identity holds after a disposition, after a disposition is revised, after a weld repair is signed off, and after a whole lot is written off.

For a repair kit, the units ever received are always fully accounted for: `qty_on_hand` plus `qty_reserved` plus `qty_issued` plus `qty_consumed_total` equals `qty_received_total`. That identity holds after a receipt, after a reservation, after an issue, after a consumption, and after a release — whether the release was requested by a planner or forced by the casting-short cascade.

Because both ledgers are recomputed rather than nudged, a compensating action restores the prior arithmetic to exactly the values it held before.

### 2.10. Occupation Windows and Interval Semantics

Casting patterns and foundries are both scarce, but they are scarce in different ways, and the API deliberately uses different interval conventions for the two.

A casting pattern is a single physical object that must be stripped and cleaned between pours, so its occupation windows are compared with **closed-interval** semantics: two windows conflict when the existing window starts at or before the new window's end *and* the new window starts at or before the existing window's end. Windows that merely touch at an endpoint therefore do conflict.

Foundry capacity, by contrast, counts how many pours are simultaneously in progress, and a pour that begins exactly when another ends is not simultaneous with it. Foundry capacity therefore uses **half-open** semantics on the interval from window start (inclusive) to window end (exclusive): two windows overlap when the existing window starts strictly before the new window's end and the new window starts strictly before the existing window's end.

The spare-parts support window uses the same half-open convention: a kit may be allocated when the logical clock is at or after `support_window_start` and strictly before `support_window_end`.

### 2.11. Test Grades and Acceptance Tolerances

Three ISO 9906 acceptance grades are recognised throughout the system, as the `test_grade` recorded on an enquiry and again on a performance test run: `GRADE_1B`, `GRADE_2B` and `GRADE_3B`. Each grade fixes three numbers that govern testing: a head tolerance band, an efficiency shortfall tolerance, and a minimum number of measured points.

`GRADE_1B` is the tightest: the head tolerance is 3.0 percent, the efficiency tolerance is 3.0 percent, and at least 5 measured points are required. `GRADE_2B` widens both tolerances to 5.0 percent while still requiring at least 5 measured points. `GRADE_3B` is the loosest: 7.0 percent on both tolerances, and only 3 measured points required. All tolerance comparisons in this specification are inclusive at the boundary, so a deviation exactly equal to the tolerance passes.

The head tolerance is two-sided — head may deviate above or below the prediction by up to the grade's percentage. The efficiency tolerance is one-sided: only a shortfall counts against the machine, and an efficiency higher than predicted is never a failure however large the excess.

## 3. Business Logic & Workflows

### 3.1. Master Data: Foundries, Hydraulic Models, Tooling and Service Configurations

Everything downstream rests on four master-data records that only a `PlatformAdmin` may author.

A **foundry** is registered with a `foundry_code` — a unique external reference between 3 and 32 characters — the partner's legal `name`, an `approved_alloys` array listing the alloy codes it is qualified to pour, and a `concurrent_pour_capacity` of at least 1 expressing how many pour windows may overlap at that site. `approved_alloys` must be non-empty and each member must be one of `CI_GG25`, `DUCTILE_GGG40`, `CD4MCU`, `DUPLEX_S31803` or `CN7M`. A new foundry is created `ACTIVE` with a `suspension_reason` of null. An admin may suspend an `ACTIVE` foundry, moving it `ACTIVE → SUSPENDED` and storing the supplied `suspension_reason`; `SUSPENDED` is terminal, so a second suspension attempt is rejected with `ERR_FOUNDRY_SUSPENDED`. Suspension is forward-looking only: existing lots are untouched, but a suspended foundry may pour no new ones.

A **hydraulic model** is the catalogue entry describing one casing and its full-diameter performance curve. It is registered with a unique `model_code`, a `generation` of at least 1, an `interchange_group` that ties generations of the same hydraulic family together for spare-parts purposes, the untrimmed `max_impeller_diameter_mm` and the smallest fittable `min_impeller_diameter_mm` (which must be greater than zero and strictly less than the maximum, both carried to two decimals), the `shutoff_head_m` at zero flow, the best-efficiency-point triple `bep_flow_m3h`, `bep_head_m` and `bep_efficiency_pct`, the catalogue `npshr_at_bep_m`, the nameplate `rated_speed_rpm` of at least 300 that serves as the affinity-law reference, the `max_flow_m3h` at the right-hand end of the allowable envelope, the rotating-assembly `rotor_mass_kg`, and the ISO 1940 `balance_grade`, which is one of `G1_0`, `G2_5` or `G6_3`. The shutoff head must exceed the best-efficiency-point head, the maximum flow must exceed the best-efficiency-point flow, and `bep_efficiency_pct` must be greater than 0 and at most 100. A new model is created `ORDERABLE`, with `superseded_by_model_id` null and all three warranty counters — `warranty_defect_count`, `application_error_count` and `no_defect_count` — at 0.

Superseding a model records the successor's identifier in `superseded_by_model_id` and moves the model to `SUPERSEDED`. Both `ORDERABLE → SUPERSEDED` and `PATTERN_CONSTRAINED → SUPERSEDED` are permitted, so a model whose tooling has all been withdrawn can still be formally replaced; a model already in the terminal `SUPERSEDED` state cannot be superseded again and is rejected with `ERR_MODEL_NOT_ORDERABLE`. The successor must exist and must not be the model itself; naming the model's own identifier is rejected with `ERR_SUCCESSOR_MODEL_INVALID`.

A **casting pattern** is the physical tooling from which castings are poured. It is registered against a `pump_model_id` naming the model it produces and a `foundry_id` naming the foundry that physically holds it, with a `pattern_code` unique across all tooling and a `wear_threshold` of at least 1. The threshold is the wear score at or above which the pattern must be withdrawn for refurbishment. A new pattern is `QUALIFIED`, with `pours_since_refurb`, `defect_pours_since_refurb`, `wear_index` and `refurb_cycles` all at 0.

A **material and seal configuration** is a released combination of wetted alloys and sealing arrangement for one model, and it is immutable once created. It names its `pump_model_id`, carries a unique `config_code`, and fixes the `casing_material` and `impeller_material` (each one of `CI_GG25`, `DUCTILE_GGG40`, `CD4MCU`, `DUPLEX_S31803` or `CN7M`), the `seal_type` (one of `SINGLE_CARTRIDGE`, `DOUBLE_CARTRIDGE`, `DUAL_PRESSURIZED` or `PACKED_GLAND`), and the API 682 `flush_plan` (one of `API_PLAN_02`, `API_PLAN_11`, `API_PLAN_23`, `API_PLAN_32` or `API_PLAN_53B`). Its `service_class` declares the duty it is rated for and is one of `CLEAN`, `CORROSIVE`, `ABRASIVE` or `CORROSIVE_ABRASIVE`. Four numeric ceilings bound the fluids it tolerates: `max_solids_pct` and `max_chloride_ppm`, both at least 0, and `max_viscosity_cst` and `max_temp_c`, both strictly greater than 0. Finally, `min_running_clearance_mm` — greater than zero, two decimals — is the minimum diametral running clearance for this material pair and anchors the assembly acceptance band described in §3.5.

Any of the seven unique codes in the system — `foundry_code`, `model_code`, `pattern_code`, `config_code`, `application_code`, `serial_number` and `kit_code` — repeating an existing value is rejected with `ERR_DUPLICATE_CODE`.

### 3.2. Enquiries and Hydraulic Sizing

An `ApplicationEngineer` opens a **duty application** — the customer enquiry — with a unique `application_code`, the `customer_name`, and the guaranteed duty point as `duty_flow_m3h` and `duty_head_m`, both strictly positive. The installation is described by `npsha_available_m`, the net positive suction head available at the pump suction, and the fluid by `specific_gravity`, `viscosity_cst`, `solids_pct`, `chloride_ppm` and `process_temp_c`; specific gravity, viscosity and temperature must be strictly positive, while solids and chloride concentration must be non-negative. The commercial terms are `min_efficiency_pct`, the contractual minimum predicted efficiency at the duty point (greater than 0 and at most 100); `test_grade`, the ISO 9906 acceptance grade the eventual performance test must satisfy; `witness_required`, a boolean stating whether the customer witnesses that test; and `service_class_required`, the service duty the chosen configuration must be rated for. A new enquiry is `OPEN`.

Sizing a pump for that enquiry produces a **selection**, and the request is compact: the engineer names a `duty_application_id`, a `pump_model_id`, a `material_seal_config_id`, and the enquiry concurrency token `expected_duty_application_version` described in §2.7. Everything else on the selection is computed. The enquiry must be `OPEN`, or the request is rejected with `ERR_DUTY_APPLICATION_NOT_OPEN`; the model must be `ORDERABLE`, or `ERR_MODEL_NOT_ORDERABLE`; and the named configuration's `pump_model_id` must equal the `pump_model_id` on the request, or `ERR_CONFIG_MODEL_MISMATCH`. Creating the selection leaves it in `DRAFT` with `proposed_by_user_id` and `approved_by_user_id` both null, and — because the enquiry's observable state has moved on — increments the enquiry's `version` by 1 even though its `status` is unchanged.

**Trimming the impeller.** The model's full-diameter curve is treated as a parabola through shutoff and the best efficiency point. Its curve constant is `shutoff_head_m` minus `bep_head_m`, divided by the square of `bep_flow_m3h`; this constant is never rounded and is reused verbatim later. The exact trim ratio is the square root of the following quotient: the numerator is `duty_head_m` plus the curve constant multiplied by the square of `duty_flow_m3h`, and the denominator is `shutoff_head_m`. `trimmed_impeller_diameter_mm` is that exact trim ratio multiplied by `max_impeller_diameter_mm`, rounded half up to one decimal place. `diameter_ratio` is then recomputed as `trimmed_impeller_diameter_mm` divided by `max_impeller_diameter_mm` — derived from the already-rounded diameter, never from the exact trim ratio — and is stored unrounded so downstream curve reconstruction is exact. `predicted_head_m` follows as the square of `diameter_ratio` multiplied by `shutoff_head_m`, minus the curve constant multiplied by the square of `duty_flow_m3h`, rounded half up to two decimal places. The order matters: deriving the predicted head from the exact trim ratio instead of the rounded diameter returns `duty_head_m` back exactly and hides the machining step the shop will actually perform.

**Predicting efficiency and power.** The trimmed best-efficiency flow is `bep_flow_m3h` multiplied by `diameter_ratio`, unrounded, and the flow ratio is `duty_flow_m3h` divided by that trimmed best-efficiency flow, also unrounded. Three penalties and one factor then act on the catalogue efficiency, and each is held unrounded. The off-best-efficiency penalty is 40.0 multiplied by the square of one minus the flow ratio, capped at 12.0 percentage points — that is, the smaller of the two values is taken. The trim penalty is one minus `diameter_ratio`, expressed in percentage points by multiplying by 100, then multiplied by 0.45, with a floor of zero so a nominally untrimmed impeller attracts no penalty. The viscosity factor is selected by tier from the enquiry's `viscosity_cst`: 1.00 at 20 centistokes or below, 0.94 above 20 and up to 100, 0.86 above 100 and up to 400, and 0.74 above 400. The abrasive penalty depends on the configuration's `service_class`: it is 0.0 for `CLEAN` and for `CORROSIVE`; for `ABRASIVE` it is 2.5 plus 0.30 multiplied by the enquiry's `solids_pct`; and for `CORROSIVE_ABRASIVE` it is 3.5 plus that same 0.30 per percent of solids. `predicted_efficiency_pct` is then computed by subtracting all three penalties from `bep_efficiency_pct`, multiplying that difference by the viscosity factor, taking the larger of the result and the absolute efficiency floor of 20.0 percent, and rounding half up to two decimals. The multiplication order is binding: the viscosity factor multiplies the already-reduced efficiency, not `bep_efficiency_pct` on its own.

`predicted_shaft_power_kw` is the enquiry's `specific_gravity` multiplied by `duty_flow_m3h`, multiplied by `predicted_head_m`, multiplied by the hydraulic power coefficient 0.00272407, then divided by `predicted_efficiency_pct` expressed as a fraction (that is, divided by a hundredth of the percentage), rounded half up to two decimals. The selection's `min_motor_kw` is `predicted_shaft_power_kw` multiplied by the motor margin of 1.10 — a ten percent headroom over predicted absorbed power — rounded half up to two decimals.

**Certifying the suction requirement.** The suction calculation deliberately breaks an apparent circularity by pinning its order in five steps. First, `npshr_catalog_m` is `npshr_at_bep_m` multiplied by the flow ratio raised to the power 1.6, rounded half up to two decimals; the flow ratio here is the same unrounded value used in the efficiency calculation. Second, `npsh_provisional_margin_m` is `npsha_available_m` minus `npshr_catalog_m`, rounded half up to two decimals. Third, `npsh_safety_factor` is selected by tier from that provisional margin: 1.35 when the provisional margin is below 0.5 metres, 1.25 when it is at least 0.5 and below 1.5 metres, 1.15 when it is at least 1.5 and below 3.0 metres, and 1.10 when it is 3.0 metres or more. Fourth, `npshr_certified_m` is `npshr_catalog_m` multiplied by the selected `npsh_safety_factor`, rounded half up to two decimals. Fifth, `npsh_margin_m` is `npsha_available_m` minus `npshr_certified_m`, rounded half up to two decimals. The tier is chosen from the *provisional* margin of step two, never from the reported margin of step five; the tier boundaries sit close enough together that the two orders genuinely disagree.

**The sizing gates.** The three calculations above all run before the business rules that read their outputs, so the gates below always compare against fully computed values. In ladder order: `process_temp_c` must not exceed `max_temp_c`, else `ERR_TEMPERATURE_LIMIT_EXCEEDED`; `chloride_ppm` must not exceed `max_chloride_ppm`, else `ERR_CHLORIDE_LIMIT_EXCEEDED`; `solids_pct` must not exceed `max_solids_pct`, else `ERR_SOLIDS_LIMIT_EXCEEDED`; `viscosity_cst` must not exceed `max_viscosity_cst`, else `ERR_VISCOSITY_LIMIT_EXCEEDED`; the configuration's `service_class` must equal the enquiry's `service_class_required`, else `ERR_SERVICE_CLASS_MISMATCH`; `duty_flow_m3h` must not exceed the model's `max_flow_m3h`, else `ERR_DUTY_FLOW_ABOVE_MAX`; the rounded `trimmed_impeller_diameter_mm` must be at least `min_impeller_diameter_mm`, else `ERR_TRIM_BELOW_MINIMUM`; the same rounded diameter must not exceed `max_impeller_diameter_mm`, else `ERR_DUTY_POINT_ABOVE_ENVELOPE`; and finally `predicted_efficiency_pct` must be at least the enquiry's `min_efficiency_pct`, compared inclusively, else `ERR_EFFICIENCY_TARGET_NOT_MET`. Note which value the two envelope gates read: the rounded diameter, not the exact trim ratio.

### 3.3. Selection Review, Approval and the Return Path

A selection travels a review cycle before it becomes a manufacturing instruction. An `ApplicationEngineer` proposes it, moving it `DRAFT → PROPOSED` and stamping `proposed_by_user_id` with the acting `X-User-ID`. The same engineer, or a colleague, may pull it back with a revision, moving it `PROPOSED → DRAFT` and clearing `proposed_by_user_id` to null — the identity is deliberately discarded so that a different engineer may re-propose without inheriting the first proposer's segregation-of-duties constraint. `DRAFT → PROPOSED → DRAFT` may be traversed any number of times.

Approval belongs exclusively to a `HydraulicApprover` and drives `PROPOSED → APPROVED`. Four conditions guard it, and they are evaluated in the ladder order of §2.6 rather than in narrative order. The acting `X-User-ID` must differ from `proposed_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; because this comparison sits above the state check, a self-approval attempt reports the conflict even when the selection is not in `PROPOSED`. The selection must then be in `PROPOSED`, else `ERR_SELECTION_INVALID_STATE`. At least one casting pattern for the selected `pump_model_id` must still be `QUALIFIED`, else `ERR_PATTERN_NOT_QUALIFIED` — approval is where tooling availability is enforced, not creation. And `npsh_margin_m` must be at least the minimum certified suction margin of 0.60 metres, compared inclusively so that a margin of exactly 0.60 approves, else `ERR_NPSH_MARGIN_INSUFFICIENT`. On success the approver's `X-User-ID` is written to `approved_by_user_id` and the parent enquiry is driven `OPEN → SELECTION_LOCKED`, its `version` incremented.

Superseding an approved selection is the escape hatch when the customer or the engineer changes their mind. It is available to an `ApplicationEngineer`, requires the selection to be `APPROVED`, and additionally requires that no build order built to this selection remains in a state other than `CLOSED`; the transition `APPROVED → SUPERSEDED` is terminal for the selection and returns the enquiry `SELECTION_LOCKED → OPEN` so a replacement can be sized against the same enquiry. That return is exactly why the enquiry accepts more than one selection over its life, and exactly why the sizing request carries a concurrency token.

The enquiry itself therefore moves through `OPEN`, `SELECTION_LOCKED`, `CONTRACTED` and finally the terminal `CLOSED`. It reaches `CONTRACTED` when a build order is opened against the approved selection, returns from `CONTRACTED` to `OPEN` as the last hop of the failed-test cascade, and reaches `CLOSED` when the finished package ships.

### 3.4. Pouring, Pattern Wear and Casting Quality

A `FoundryPartner` records a **casting lot** against a `pattern_asset_id` and a `foundry_id`, supplying the melt `heat_number`, the `alloy_code` poured, the `qty_poured`, and the occupation window as `pour_window_start` and `pour_window_end`. The `foundry_id` in the body must equal the caller's `X-User-ID`, else `ERR_FOUNDRY_SCOPE_VIOLATION`. The pattern must be `QUALIFIED`; pouring from tooling that is `WORN`, `IN_REFURB` or `RETIRED` is rejected with `ERR_PATTERN_INVALID_STATE`. The foundry must be `ACTIVE`, else `ERR_FOUNDRY_SUSPENDED`. The `alloy_code` must be a member of that foundry's `approved_alloys`, else `ERR_ALLOY_NOT_APPROVED`.

Two scheduling rules then apply, with the interval conventions of §2.10. First, no other lot on the same pattern whose status is anything other than the terminal `SCRAPPED` may occupy an overlapping window under closed-interval comparison — a conflict exists when the existing window starts at or before the new window's end and the new window starts at or before the existing window's end, so windows that merely touch at an endpoint conflict, giving the pattern its strip-and-clean time. A conflict is rejected with `ERR_PATTERN_WINDOW_CONFLICT`. Second, the count of lots at the same `foundry_id` whose status is not `SCRAPPED` and whose windows overlap the new window under half-open comparison — the existing window starting strictly before the new window's end and the new window starting strictly before the existing window's end — must be strictly less than that foundry's `concurrent_pour_capacity`, else `ERR_FOUNDRY_POUR_CAPACITY_EXCEEDED`. Because foundry capacity is half-open, a lot beginning exactly when another ends does not count against it, even though the same pair of windows would conflict on a shared pattern. Finally, `pour_window_start` must be strictly before `pour_window_end`, else `ERR_INVALID_WINDOW`.

A new lot is `POURED`, with `qty_scrapped` and `qty_rework_pending` at 0, `qty_accepted` equal to `qty_poured`, and `committed_build_count` at 0. Recording the pour also advances the tooling: `pours_since_refurb` on the pattern is incremented by 1 and the pattern's `version` is bumped.

**Pattern wear.** The wear score is a weighted count, not a decay curve in disguise. `wear_index` is `pours_since_refurb` plus twice `defect_pours_since_refurb` — a lot that produced a critical defect counts three times as heavily against the tooling as a clean lot, because the pattern is implicated in the defect. `defect_pours_since_refurb` advances by 1 on the *first* critical defect reported against a given lot poured from that pattern since the last completed refurbishment; further critical defects on the same lot do not advance it again. Whenever either counter moves, `wear_index` is recomputed, and if the pattern is `QUALIFIED` and its `wear_index` has reached or passed `wear_threshold`, the pattern moves `QUALIFIED → WORN`. If that leaves the pattern's model with no `QUALIFIED` pattern at all, the model is driven `ORDERABLE → PATTERN_CONSTRAINED` in the same request, after which new selections against it are refused. Both hops bump their entity's `version`.

Tooling recovery is a `PlatformAdmin` cycle. Starting a refurbishment moves the pattern `WORN → IN_REFURB` and requires that no lot on that pattern is still in `POURED`, `INSPECTED`, `REWORK` or `QUARANTINED`. Completing a refurbishment moves it `IN_REFURB → QUALIFIED`, resets `pours_since_refurb`, `defect_pours_since_refurb` and `wear_index` all to 0, increments `refurb_cycles` by 1, and — when this is the model's only `QUALIFIED` pattern — drives the model `PATTERN_CONSTRAINED → ORDERABLE`. Retirement is permitted from either `QUALIFIED` or `WORN`, subject to the same requirement that no lot on the pattern is still in `POURED`, `INSPECTED`, `REWORK` or `QUARANTINED`; `QUALIFIED → RETIRED` and `WORN → RETIRED` are both terminal, and either may drive the model `ORDERABLE → PATTERN_CONSTRAINED` when no qualified pattern remains.

**Casting defects.** Either a `FoundryPartner` or a `QualityInspector` may report a defect against a lot, supplying a `defect_code`, a `defect_type` from `POROSITY`, `SHRINKAGE`, `INCLUSION`, `COLD_SHUT`, `MISRUN` and `CORE_SHIFT`, a `severity` of `MINOR`, `MAJOR` or `CRITICAL`, and an `affected_qty` of at least 1 that must not exceed the lot's `qty_accepted` at report time, else `ERR_AFFECTED_QTY_EXCEEDS_LEDGER`. A lot in the terminal `SCRAPPED` state accepts no further reports and yields `ERR_CASTING_LOT_INVALID_STATE`. A new defect is `REPORTED` with `disposition` null, `dispositioned_by_user_id` null, and `reported_by_user_id` taken from the acting `X-User-ID`. Reporting alone leaves the lot's piece ledger untouched; only a disposition moves pieces. A `CRITICAL` severity, however, immediately feeds the wear machinery described above, and can therefore withdraw the tooling and constrain the model inside the reporting request.

A `QualityInspector` then dispositions the defect, and the three outcomes diverge sharply. `USE_AS_IS` moves the defect `REPORTED → DISPOSITIONED_USE_AS_IS`, sets `disposition` to `USE_AS_IS`, records `dispositioned_by_user_id`, and leaves the lot's piece ledger entirely unchanged; it is the only disposition that carries a segregation-of-duties requirement, namely that the acting `X-User-ID` differ from `reported_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. `REPAIR_WELD` moves the defect `REPORTED → DISPOSITIONED_REPAIR`, sets `disposition` to `REPAIR_WELD`, and moves the affected pieces into the weld-repair column. `SCRAP` moves the defect `REPORTED → DISPOSITIONED_SCRAP`, sets `disposition` to `SCRAP`, and writes the affected pieces off. Both `REPAIR_WELD` and `SCRAP` reconcile the lot ledger and bump the lot's `version` as well as the defect's, and both can open the casting-short cascade. `DISPOSITIONED_USE_AS_IS` is terminal for the defect.

**The piece ledger.** The lot's ledger is a full recompute from the defect rows, never an increment, which is what makes compensation exact. `qty_scrapped` is the sum of `affected_qty` over every defect on the lot whose status is `DISPOSITIONED_SCRAP`. `qty_rework_pending` is the sum of `affected_qty` over every defect whose status is `DISPOSITIONED_REPAIR`. `qty_accepted` is `qty_poured` minus `qty_scrapped` minus `qty_rework_pending`. Defects in `REPORTED`, `DISPOSITIONED_USE_AS_IS` and `REPAIR_VERIFIED` contribute nothing to either sum. Separately, `committed_build_count` is the count of build orders bound to the lot whose status is neither `CLOSED` nor `CASTING_SHORT`. The ledger is recomputed on a disposition, on a revised disposition, on a weld-repair sign-off, and on a whole-lot write-off, and the conservation identity of §2.9 is checked after each.

Two compensating steps close the round trip. An inspector may revise a scrap decision to a weld repair, moving the defect `DISPOSITIONED_SCRAP → DISPOSITIONED_REPAIR`, which subtracts the `affected_qty` from the scrap column, adds it to the rework column, sets `disposition` to `REPAIR_WELD`, recomputes the ledger and bumps both the lot's and the defect's `version`. The inspector then signs off the completed weld, moving the defect `DISPOSITIONED_REPAIR → REPAIR_VERIFIED`, which removes the `affected_qty` from the rework column, recomputes the ledger, bumps both versions, and may return the lot to acceptance. After that second step the pieces are back in the accepted column and the scrap column holds exactly what it held before the scrap decision was ever taken. `REPAIR_VERIFIED` is terminal for the defect.

**The lot lifecycle.** An inspector inspects a lot from either `POURED` or `REWORK`, in both cases landing on `INSPECTED`. Acceptance drives `INSPECTED → ACCEPTED` and requires two things: no defect on the lot may still be in `REPORTED`, else `ERR_OPEN_DEFECTS_PRESENT`, and `qty_accepted` must be at least 1, else `ERR_NO_ACCEPTABLE_CASTINGS`. A scrap or weld-repair disposition can push a lot from either `INSPECTED` or `ACCEPTED` into `QUARANTINED`, but only when, after the ledger has been reconciled, `qty_accepted` has fallen below the larger of 1 and `committed_build_count` — that is, a lot with no committed builds is quarantined only when it can no longer yield a single good casting, whereas a lot carrying commitments is quarantined as soon as it can no longer cover them. From `QUARANTINED`, the inspector may start rework, moving `QUARANTINED → REWORK`; may write the lot off entirely, moving `QUARANTINED → SCRAPPED`, which sets `qty_scrapped` to `qty_poured`, `qty_rework_pending` to 0 and `qty_accepted` to 0; or may see the lot restored automatically. That restoration is the compensation path: signing off a weld repair drives `QUARANTINED → ACCEPTED` when no defect on the lot remains in `REPORTED`, `DISPOSITIONED_REPAIR` or `DISPOSITIONED_SCRAP` and, after reconciliation, `qty_accepted` has reached at least the larger of 1 and `committed_build_count`. `SCRAPPED` is terminal.

### 3.5. Build Orders, Assembly Standards and the Casting-Short Cascade

A `ProductionPlanner` opens a **build order** against a `selection_id` and a `casting_lot_id`, with a `serial_number` unique across all build orders. The selection must be `APPROVED`, else `ERR_SELECTION_NOT_APPROVED`; the lot must be `ACCEPTED`, else `ERR_CASTING_LOT_NOT_ACCEPTED`; and the lot's pattern must produce the model the selection chose — the pattern's `pump_model_id` must equal the selection's `pump_model_id`, else `ERR_LOT_MODEL_MISMATCH`. A new build order is `PLANNED` with `rework_cycles` at 0 and `running_clearance_mm`, `residual_unbalance_g_mm`, `seal_flush_plan_installed` and `allowable_unbalance_g_mm` all null. Opening it increments the lot's `committed_build_count` by 1 and the lot's `version`, and drives the enquiry `SELECTION_LOCKED → CONTRACTED`.

**Assembly.** Recording machining and assembly results moves the order `PLANNED → ASSEMBLED` and carries three measurements: the `running_clearance_mm` measured diametrally at assembly, the `residual_unbalance_g_mm` of the rotating assembly, and the `seal_flush_plan_installed`, which is the plan actually piped and must be one of `API_PLAN_02`, `API_PLAN_11`, `API_PLAN_23`, `API_PLAN_32` or `API_PLAN_53B`. All three are stored on the order, and `allowable_unbalance_g_mm` is computed and stored alongside them.

The balance allowance follows ISO 1940. The balance quality number is taken from the model's `balance_grade`: 1.0 for `G1_0`, 2.5 for `G2_5` and 6.3 for `G6_3`. `allowable_unbalance_g_mm` is that quality number multiplied by the ISO 1940 coefficient 9549, multiplied by the model's `rotor_mass_kg`, divided by the model's `rated_speed_rpm`, rounded half up to two decimals. Acceptance is inclusive: `residual_unbalance_g_mm` equal to `allowable_unbalance_g_mm` passes, and anything greater is rejected with `ERR_UNBALANCE_EXCEEDS_ALLOWANCE`.

The clearance acceptance band is anchored on the selection's material and seal configuration. Its lower edge is that configuration's `min_running_clearance_mm` exactly; its upper edge is `min_running_clearance_mm` plus the standard band width of 0.15 millimetres, rounded half up to two decimals. Both edges are inclusive, so a measured `running_clearance_mm` sitting exactly on either edge passes, and a value outside the band is rejected with `ERR_CLEARANCE_OUT_OF_BAND`. Finally, `seal_flush_plan_installed` must equal the configuration's `flush_plan`, else `ERR_FLUSH_PLAN_MISMATCH`. In ladder order the unbalance check precedes the clearance check, which precedes the flush-plan check.

**Rework.** When a performance test finds the machine out of hydraulic tolerance, the order is driven from either `ASSEMBLED` or `TESTED` into `REWORK_REQUIRED`. A planner signs off the loop to return it `REWORK_REQUIRED → ASSEMBLED`, incrementing `rework_cycles` by 1. The loop is bounded: the sign-off requires `rework_cycles` to be strictly less than the limit of 2 completed loops, so the third attempt to close a loop is rejected with `ERR_REWORK_LIMIT_EXCEEDED`.

**Casting shortage.** When the bound lot moves to `QUARANTINED` because its `qty_accepted` has fallen below its `committed_build_count`, exactly one build order is stranded: the newest non-terminal order bound to that lot, selected from those in `PLANNED`, `ASSEMBLED`, `TESTED` or `REWORK_REQUIRED`, ordered by `created_at` descending. That order is driven to `CASTING_SHORT`, and the lot's `committed_build_count` is decremented by 1. If the stranded order was in `ASSEMBLED` or `TESTED` and already carries an engineered package, the cascade continues into that package as described in §3.7. Whatever the originating state, the order's `version` is incremented.

Recovery from `CASTING_SHORT` is a re-binding: the planner supplies a replacement `casting_lot_id`, and the order moves `CASTING_SHORT → PLANNED`. The replacement lot must be `ACCEPTED`, else `ERR_CASTING_LOT_NOT_ACCEPTED`, and its pattern's `pump_model_id` must match the selection's `pump_model_id`, else `ERR_LOT_MODEL_MISMATCH`. The replacement lot's `committed_build_count` is incremented by 1, and — because the physical casting has changed — `running_clearance_mm`, `residual_unbalance_g_mm`, `seal_flush_plan_installed` and `allowable_unbalance_g_mm` are all reset to null, so assembly must be recorded again from scratch.

A build order reaches the terminal `CLOSED` state only when its package ships, which also decrements the lot's `committed_build_count` by 1. Kit allocations may only be raised against a build order that is neither `CLOSED` nor `CASTING_SHORT`; an attempt against either is rejected with `ERR_BUILD_ORDER_INVALID_STATE`.

### 3.6. Performance Testing: the Certified Curve and Suction Verification

A `TestEngineer` opens a **performance test run** against a `build_order_id`, naming the `test_speed_rpm` the bed will actually turn at (at least 300), the `correction_basis` governing how measurements become the reported curve, the `test_grade` applied to this run, and `witness_required`, the boolean marking a witnessed contractual test. The build order must be `ASSEMBLED`, else `ERR_BUILD_ORDER_NOT_ASSEMBLED`.

A test run is unusual in this API in carrying **three independent state dimensions**, which advance on the same requests but whose values cannot be derived from one another. `run_state` tracks execution and moves `OPEN → POINTS_LOCKED → EVALUATED → CERTIFIED`, with an `EVALUATED → OPEN` reopen cycle. `hydraulic_status` tracks head and efficiency acceptance and moves from `NOT_EVALUATED` to either `WITHIN_TOLERANCE` or `OUT_OF_TOLERANCE`. `npsh_status` tracks suction performance and moves from `NOT_VERIFIED` to either `VERIFIED` or `REJECTED`. A new run starts `OPEN`, `NOT_EVALUATED` and `NOT_VERIFIED`, with `speed_ratio`, `head_at_guarantee_m`, `power_at_guarantee_kw`, `efficiency_at_guarantee_pct`, `head_deviation_pct`, `efficiency_deviation_pct` and `npshr_tested_m` all null.

Measured points are appended one at a time while `run_state` is `OPEN`; appending to a run in any other run state is rejected with `ERR_TEST_RUN_INVALID_STATE`. Each **test point** carries a strictly positive `measured_flow_m3h`, `measured_head_m` and `measured_power_kw`, an optional `measured_npsh3_m` holding the three-percent-head-drop suction measurement, and an optional `is_npsh_point` boolean that defaults to false and marks the single point carrying that suction measurement; `measured_npsh3_m` is required whenever `is_npsh_point` is true. Test points are immutable and append-only.

Freezing the point set drives `run_state` from `OPEN` to `POINTS_LOCKED`, after which no further point may be added. Two conditions guard it: the run must hold at least the grade's minimum point count from §2.11 — 5 points for `GRADE_1B`, 5 for `GRADE_2B`, 3 for `GRADE_3B` — else `ERR_INSUFFICIENT_TEST_POINTS`; and exactly one point of the run must have `is_npsh_point` true and carry a non-null `measured_npsh3_m`, with both zero such points and more than one such point rejected as `ERR_NPSH_TEST_POINT_MISSING`.

**Building the reported curve.** Evaluation drives `run_state` from `POINTS_LOCKED` to `EVALUATED`, and it is where the two correction bases diverge. Under `RATED_SPEED_CORRECTED` the speed factor is the model's `rated_speed_rpm` divided by the run's `test_speed_rpm`, and the affinity laws are applied to every measured point before anything else happens: reported flow scales with the speed factor, reported head with its square, reported power with its cube, and the reported suction figure with its square. Under `AS_TESTED` the speed factor is forced to exactly 1, so measured flow, head, power and suction figure are reported unchanged even when `test_speed_rpm` differs from `rated_speed_rpm`, and the guarantee point is interpolated on the raw measured curve. The consequence is deliberate and is the whole reason the field exists: on an under-speed test, correcting to rated speed lifts and shifts the whole curve, so the identical measured points can land inside the grade's head tolerance under `RATED_SPEED_CORRECTED` while failing under `AS_TESTED`. The stored `speed_ratio` is the speed factor rounded half up to four decimals, but the reported point set is built from the unrounded factor.

Each reported point value — flow, head, power, and, on the designated suction point only, the suction figure — is rounded half up to two decimals as it is produced. The reported points are then sorted by reported flow ascending, with ties on reported flow broken by the point's `created_at` ascending. The guarantee flow is the enquiry's `duty_flow_m3h`, reached from the run through its build order and that order's selection, and it must lie between the minimum and maximum reported flow inclusive, else `ERR_GUARANTEE_FLOW_NOT_BRACKETED`.

Interpolation runs on the already-rounded reported values, over the single segment that brackets the guarantee flow — the point immediately at or below it and the point immediately at or above it. The interpolation fraction is the guarantee flow minus the lower point's reported flow, divided by the upper point's reported flow minus the lower point's reported flow, and is held unrounded. When the guarantee flow coincides exactly with a reported point, that point's values are used verbatim. `head_at_guarantee_m` is the lower point's reported head plus the fraction multiplied by the difference between the two reported heads, rounded half up to two decimals; `power_at_guarantee_kw` is computed the same way from the two reported powers. `efficiency_at_guarantee_pct` is then the enquiry's `specific_gravity` multiplied by the guarantee flow, multiplied by `head_at_guarantee_m`, multiplied by the hydraulic power coefficient 0.00272407, divided by `power_at_guarantee_kw`, multiplied by 100, rounded half up to two decimals. `npshr_tested_m` is simply the reported suction figure of the single point flagged `is_npsh_point`.

Two signed deviations close the arithmetic. `head_deviation_pct` is `head_at_guarantee_m` minus the selection's `predicted_head_m`, divided by `predicted_head_m`, multiplied by 100, rounded half up to two decimals. `efficiency_deviation_pct` is `efficiency_at_guarantee_pct` minus the selection's `predicted_efficiency_pct`, divided by `predicted_efficiency_pct`, multiplied by 100, rounded half up to two decimals.

**Setting the two result dimensions.** Both are set by the same evaluation request, independently of each other and of `run_state`. `hydraulic_status` becomes `WITHIN_TOLERANCE` when `head_deviation_pct` is at least the negative of the grade's head tolerance and at most the positive of that same tolerance, *and* `efficiency_deviation_pct` is at least the negative of the grade's efficiency tolerance; both comparisons are inclusive and a positive efficiency deviation is never a failure. Otherwise `hydraulic_status` becomes `OUT_OF_TOLERANCE` — that is, whenever the head deviation falls below the negative tolerance, or rises above the positive tolerance, or the efficiency deviation falls below the negative efficiency tolerance. `npsh_status` becomes `VERIFIED` when `npshr_tested_m` is at most the selection's `npshr_catalog_m` plus the suction test tolerance of 0.30 metres, compared inclusively, and `REJECTED` when it exceeds that sum.

A `WITHIN_TOLERANCE` result triggers no cascade and leaves the build order where it is. An `OUT_OF_TOLERANCE` result opens the failed-test cascade in the same request: the build order is driven from `ASSEMBLED` or `TESTED` into `REWORK_REQUIRED`, which drives the selection `APPROVED → UNDER_REVIEW`, which drives the enquiry `CONTRACTED → OPEN`. All three entities have their `version` incremented. A `REJECTED` suction result triggers no cascade at all; it simply blocks certification. A selection sitting in `UNDER_REVIEW` re-enters the review cycle through a fresh proposal, moving `UNDER_REVIEW → PROPOSED` and stamping `proposed_by_user_id` again, which closes the `APPROVED → UNDER_REVIEW → PROPOSED → APPROVED` loop.

Certification drives `run_state` from `EVALUATED` to the terminal `CERTIFIED` and requires both result dimensions to have passed: `hydraulic_status` must be `WITHIN_TOLERANCE`, else `ERR_HYDRAULIC_OUT_OF_TOLERANCE`, and `npsh_status` must be `VERIFIED`, else `ERR_NPSH_NOT_VERIFIED`. Certification drives the build order `ASSEMBLED → TESTED`.

Reopening a run drives `run_state` from `EVALUATED` back to `OPEN`, resets `hydraulic_status` to `NOT_EVALUATED` and `npsh_status` to `NOT_VERIFIED`, and clears `speed_ratio`, `head_at_guarantee_m`, `power_at_guarantee_kw`, `efficiency_at_guarantee_pct`, `head_deviation_pct`, `efficiency_deviation_pct` and `npshr_tested_m` all to null. Points already recorded are retained, and new points may be appended alongside them.

### 3.7. Engineered Packages: Motor Sizing, Guarantee Basis and Shipment

A `ProductionPlanner` engineers a **pump package** around a tested unit, naming the `build_order_id` and the `test_run_id` whose curve the package will ship against, and supplying the `baseplate_code` drawing reference, the installed `motor_kw`, the `motor_frame` designation, the `control_type` (one of `DOL_STARTER`, `SOFT_STARTER`, `VFD` or `NONE`), and the contractual `promised_ship_date`. The build order must be `TESTED`, else `ERR_BUILD_ORDER_NOT_TESTED`, and the named test run must belong to that same build order, else `ERR_TEST_RUN_BUILD_MISMATCH`. A new package is `CONFIGURED`, with `guarantee_basis` null, `application_error_flagged` false and `actual_ship_date` null.

The motor requirement is fixed at package creation, and which reference power it uses depends on the witness flag of the named test run — because that flag is what will later determine which curve the warranty is written against. When the run's `witness_required` is true, the package's `min_motor_kw` is the run's `power_at_guarantee_kw` multiplied by the motor margin of 1.10, rounded half up to two decimals. When the run's `witness_required` is false, `min_motor_kw` is instead the selection's `predicted_shaft_power_kw` multiplied by that same 1.10 margin, rounded half up to two decimals. The named run must already be at least `EVALUATED` so that `power_at_guarantee_kw` is populated. The supplied `motor_kw` must be at least the computed `min_motor_kw`, compared inclusively, else `ERR_MOTOR_UNDERSIZED`.

Release drives the package `CONFIGURED → RELEASED` and requires the associated test run's `run_state` to be `CERTIFIED`, else `ERR_TEST_RUN_NOT_CERTIFIED`. Release is where the warranty reference curve is frozen: `guarantee_basis` is set to `CERTIFIED_CURVE` when the run's `witness_required` is true, and to `SELECTION` when it is false. That single field decides, years later, whether a field complaint is measured against the machine that was actually tested or against the catalogue trim curve that was promised on paper.

Shipment drives the package `RELEASED → SHIPPED`, stores the supplied `actual_ship_date` — which anchors the warranty clock — drives the build order `TESTED → CLOSED` while decrementing the bound lot's `committed_build_count` by 1, and drives the enquiry `CONTRACTED → CLOSED`. `SHIPPED` is terminal for the package.

A package may also be interrupted. As the third hop of the casting-short cascade, a package in either `CONFIGURED` or `RELEASED` is driven to `HELD` when its build order moves to `CASTING_SHORT`; the hold clears `promised_ship_date` to null and releases every still-reserved kit allocation on the same build order, as described in §3.8. A planner lifts the hold with a release-hold action that drives `HELD → CONFIGURED`, permitted only once the build order is no longer in `CASTING_SHORT`. `promised_ship_date` stays null across that cycle and is not restored; a new commitment must be captured on a fresh package if the customer requires one.

### 3.8. Spare Parts: Interchangeability, Stock and Allocation Charges

A `PlatformAdmin` catalogues a **repair kit** against the `pump_model_id` it was originally drawn for, with a unique `kit_code`, the `interchange_group` it fits, and its generation coverage as `gen_min` and `gen_max` (each at least 1, with `gen_max` at least `gen_min`) plus a `preferred_generation` inside that inclusive range for which the kit is dimensionally optimal. Commercially it carries a `unit_price` greater than zero at two decimals and a `substitution_penalty_pct` of at least 0, the price uplift charged when the kit is fitted outside its preferred generation. Its availability period runs from an inclusive `support_window_start` to an exclusive `support_window_end`, which must be strictly after the start, else `ERR_INVALID_WINDOW`. A new kit is `ACTIVE` with `qty_received_total`, `qty_on_hand`, `qty_reserved`, `qty_issued` and `qty_consumed_total` all 0.

A `ProductionPlanner` receives units into stock by supplying a `qty` of at least 1, which is added to both `qty_on_hand` and `qty_received_total` and bumps the kit's `version`. An admin may withdraw a kit from the catalogue, driving `ACTIVE → DISCONTINUED`; the state is terminal, so a second withdrawal attempt yields `ERR_REPAIR_KIT_DISCONTINUED`, and receipts against a discontinued kit are refused with the same code. Existing allocations against a discontinued kit are unaffected.

**Explicit reservation.** A planner may reserve units of a named kit by supplying the `repair_kit_id`, the `build_order_id` the kit is allocated against, a `requested_qty` of at least 1, and the kit concurrency token `expected_repair_kit_version`. The kit must be `ACTIVE`, else `ERR_REPAIR_KIT_DISCONTINUED`. Four further conditions apply in ladder order: the kit's `interchange_group` must equal the `interchange_group` of the build order's model, else `ERR_KIT_GROUP_MISMATCH`; that model's `generation` must lie inside the kit's inclusive coverage from `gen_min` to `gen_max`, else `ERR_KIT_GENERATION_NOT_COVERED`; the logical clock must be at or after `support_window_start` and strictly before `support_window_end`, else `ERR_KIT_SUPPORT_WINDOW_EXPIRED`; and `qty_on_hand` must be at least `requested_qty`, else `ERR_KIT_STOCK_INSUFFICIENT`. A reservation created this way is `RESERVED` with `selected_by` set to `EXPLICIT`.

**Selector-driven reservation.** Alternatively the planner may ask the interchange selector to choose, supplying only a `requested_qty` of at least 1; no concurrency token is taken because the client never names a kit. The selector first builds a candidate set of every repair kit satisfying all of the following against the build order's model: its `status` is `ACTIVE`; its `interchange_group` equals the model's `interchange_group`; the model's `generation` is at least `gen_min` and at most `gen_max`; the logical clock is at or after `support_window_start` and strictly before `support_window_end`; and its `qty_on_hand` is at least `requested_qty`. If that candidate set is empty the request is rejected with `ERR_NO_INTERCHANGEABLE_KIT` — the same conditions that produce distinct errors on an explicit reservation are simply filter criteria here.

The candidate set is then ranked in three ordered levels. First, kits whose `preferred_generation` equals the model's `generation` rank ahead of those whose does not — an exact-preference flag of 1 sorting before a flag of 0. Second, among kits tied on that flag, the lower `substitution_penalty_pct` ranks ahead. Third, among kits still tied, the lower `unit_price` ranks ahead. When all three levels tie, the earlier `created_at` wins. A kit's `id` plays no part in eligibility, ranking or tie-breaking; `created_at` ascending is the only fallback. The winner becomes the allocation's `repair_kit_id`, and `selected_by` is set to `SELECTOR`.

**Charging the allocation.** Both reservation routes then price the allocation identically. `substitution_penalty_applied_pct` is the kit's `substitution_penalty_pct` when the kit's `preferred_generation` differs from the build order model's `generation`, and 0 otherwise. `parts_extended` is `requested_qty` multiplied by the kit's `unit_price`, multiplied by one plus a hundredth of `substitution_penalty_applied_pct`, rounded half up to two decimals. `handling_rate` is then selected by tier from `parts_extended`: 0.12 when `parts_extended` is 1000 or less, 0.08 when it is above 1000 and at most 5000, 0.05 when it is above 5000 and at most 20000, and 0.03 when it exceeds 20000. The tier is keyed on `parts_extended` — after the substitution penalty but before any handling fee — and never on the pre-penalty extended value or on the final charge; at the 5000 boundary those keys select different tiers. `handling_fee` is `parts_extended` multiplied by `handling_rate`, rounded half up to two decimals, and `total_charge` is `parts_extended` plus `handling_fee`, rounded half up to two decimals.

Creating either kind of reservation moves `requested_qty` units out of the kit's `qty_on_hand` and into its `qty_reserved`, and increments the kit's `version`.

**Moving the reservation.** A planner issues reserved units to the shop floor, driving the allocation `RESERVED → ISSUED` and moving `requested_qty` from `qty_reserved` to `qty_issued`. Issued units are later booked as consumed, driving `ISSUED → CONSUMED` and moving `requested_qty` from `qty_issued` to `qty_consumed_total`. Alternatively a reservation may be given up, driving `RESERVED → RELEASED` and moving `requested_qty` from `qty_reserved` back to `qty_on_hand`, which restores the pre-reservation stock position exactly. The same `RESERVED → RELEASED` transition, with the same stock movement, is what the casting-short cascade performs on every still-reserved allocation of a build order whose package goes on hold — the cascade path and the planner-initiated path are identical in effect. Every one of these transitions increments both the kit's `version` and the allocation's `version`. `CONSUMED` and `RELEASED` are both terminal.

### 3.9. Field Troubleshooting, Warranty Adjudication and Settlement

An `ApplicationEngineer` raises a **warranty claim** against a shipped package by naming the `pump_package_id` and reporting what the field engineer measured: `as_found_flow_m3h`, `as_found_head_m`, `as_found_npsha_m`, `as_found_solids_pct`, `as_found_viscosity_cst` and `as_found_speed_rpm`. Flow, head, suction head and viscosity must all be strictly positive, solids concentration must be non-negative, and the measured speed must be at least 300. The commercial side of the claim is `claim_lines`, a non-empty array in which every element carries a `line_code`, a `category` of `PARTS`, `LABOUR`, `FREIGHT` or `DOWNTIME`, and a strictly positive `gross_amount`; an empty array, or any element whose `gross_amount` is not strictly positive, is rejected with `ERR_EMPTY_CLAIM_LINES`. The package must be `SHIPPED`, else `ERR_PACKAGE_NOT_SHIPPED`.

Two values are stamped at submission and never re-derived afterwards. `months_since_ship` is the number of *whole* months from the package's `actual_ship_date` to the logical clock at claim creation, with any partial month discarded rather than rounded up. `coverage_factor` is selected by tier from that stamped age: 1.00 when `months_since_ship` is 12 or less, 0.60 when it is above 12 and at most 24, and 0.30 when it is above 24 and at most 36. A claim whose `months_since_ship` exceeds the 36-month warranty period — three years from the ship date — is rejected outright with `ERR_WARRANTY_EXPIRED`, which is why no coverage tier of zero is ever reachable. The claim is created `SUBMITTED`, with `submitted_by_user_id` from the acting `X-User-ID`, `adjudicated_by_user_id` and `info_request_note` null, `application_error_flags` an empty list, and `liability_basis`, `expected_head_m`, `head_shortfall_pct`, `determination`, `settlement_subtotal`, `admin_fee` and `settlement_total` all null.

A `WarrantyAdjudicator` takes the claim in hand, driving `SUBMITTED → UNDER_ADJUDICATION`. From there the adjudicator may return it to the field for more information, driving `UNDER_ADJUDICATION → INFO_REQUESTED` and storing the supplied `info_request_note`, and later resume, driving `INFO_REQUESTED → UNDER_ADJUDICATION` and clearing `info_request_note` back to null. That loop is unbounded and may be traversed any number of times.

**Determining liability.** Adjudication is where the two guarantee bases diverge, and the divergence is the point of the whole design. `liability_basis` is copied from the package's `guarantee_basis` as fixed at release. Under the `CERTIFIED_CURVE` basis — the package shipped against a witnessed test — `expected_head_m` is interpolated from the test run's reported point set at `as_found_flow_m3h`, that point set being rebuilt exactly as the run's own `correction_basis` builds it; the promise is the measured machine. Under the `SELECTION` basis — the package shipped against an unwitnessed production test — `expected_head_m` is instead the square of the selection's `diameter_ratio` multiplied by the model's `shutoff_head_m`, minus the model's parabolic curve constant multiplied by the square of `as_found_flow_m3h`, rounded half up to two decimals, where the curve constant is again `shutoff_head_m` minus `bep_head_m` divided by the square of `bep_flow_m3h`; the promise is the catalogue trim curve. The two bases agree closely near the duty point and diverge away from it, so identical field data can yield one determination on one basis and the opposite determination on the other.

`head_shortfall_pct` is then `as_found_head_m` minus `expected_head_m`, divided by `expected_head_m`, multiplied by 100, rounded half up to two decimals.

The installation is examined next, and `application_error_flags` is built as an ordered list in exactly this sequence, because the order is observable in the response. `SOLIDS_EXCEEDS_CONFIG` is appended when `as_found_solids_pct` exceeds the configuration's `max_solids_pct`. `VISCOSITY_EXCEEDS_CONFIG` is appended when `as_found_viscosity_cst` exceeds `max_viscosity_cst`. `NPSHA_BELOW_CERTIFIED` is appended when `as_found_npsha_m` is strictly less than the selection's `npshr_certified_m` plus the minimum certified suction margin of 0.60 metres. `SPEED_ABOVE_RATED` is appended when `as_found_speed_rpm` exceeds the model's `rated_speed_rpm`.

`determination` is then decided by evaluating three conditions top to bottom, first match winning. It is `NO_DEFECT_FOUND` when `head_shortfall_pct` is at least the negative of the head tolerance for the test run's `test_grade` — the machine is delivering what it promised, within the grade's band. Failing that, it is `APPLICATION_ERROR` when `application_error_flags` is non-empty — the machine is short, but the installation explains why. Failing both, it is `MANUFACTURING_DEFECT`.

The three outcomes are a genuine three-way fork with divergent side effects, and none of them may be adjudicated by the person who submitted the claim: the acting `X-User-ID` must differ from `submitted_by_user_id`, else `ERR_ADJUDICATOR_CONFLICT`. All three store `liability_basis`, `expected_head_m`, `head_shortfall_pct`, `application_error_flags` and `determination`, record `adjudicated_by_user_id`, and increment exactly one of the model's three warranty counters along with the model's `version`.

- `NO_DEFECT_FOUND` drives the claim `UNDER_ADJUDICATION → ADJUDICATED_NO_DEFECT`, increments the model's `no_defect_count` by 1, and leaves `settlement_subtotal`, `admin_fee` and `settlement_total` null. The state is terminal.
- `APPLICATION_ERROR` drives the claim `UNDER_ADJUDICATION → ADJUDICATED_APPLICATION_ERROR`, increments the model's `application_error_count` by 1, and is the only branch that touches the package: it sets `application_error_flagged` to true and increments the package's `version`. It too leaves `settlement_subtotal`, `admin_fee` and `settlement_total` null, and it too is terminal.
- `MANUFACTURING_DEFECT` drives the claim `UNDER_ADJUDICATION → ADJUDICATED_MANUFACTURING`, increments the model's `warranty_defect_count` by 1, does not touch the package, and is the only branch from which settlement is reachable.

**Settling.** From `ADJUDICATED_MANUFACTURING` the adjudicator settles the claim, driving `ADJUDICATED_MANUFACTURING → SETTLED`. The rounding order here is pinned and is the whole difficulty of the calculation: each claim line is settled and rounded on its own, and only then are the lines summed. Working through `claim_lines` in the order supplied in the original request, each line's settled amount is its `gross_amount` multiplied by the stamped `coverage_factor`, rounded half up to two decimals. `settlement_subtotal` is the sum of those per-line settled amounts, rounded half up to two decimals. `admin_fee` is `settlement_subtotal` multiplied by the administration rate of 0.075 — seven and a half percent of the covered amount — rounded half up to two decimals. `settlement_total` is `settlement_subtotal` plus `admin_fee`, rounded half up to two decimals. Summing the gross amounts first and rounding once at the end produces a different total and is not what the contract promises. `SETTLED` is terminal.

## 4. Endpoint Definitions

Operations that bring a new resource into existence return `201 Created`. Operations that modify an existing resource — including every state-transition action, every ledger movement and every reconciliation — return `200 OK`, as do all read operations. In the table below, "All roles" means all eight declared roles: `PlatformAdmin`, `ApplicationEngineer`, `HydraulicApprover`, `FoundryPartner`, `QualityInspector`, `TestEngineer`, `ProductionPlanner` and `WarrantyAdjudicator`. Request and response payloads are not restated here; they are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |
| GET | `/_clock` | Read the current logical clock value | All roles |
| POST | `/foundries` | Register a foundry partner | PlatformAdmin |
| GET | `/foundries` | List foundries | All roles |
| GET | `/foundries/{id}` | Read one foundry | All roles |
| POST | `/foundries/{id}/suspend` | Suspend a foundry so it may no longer pour new lots | PlatformAdmin |
| POST | `/pump-models` | Register a hydraulic model with its full-diameter curve reference points | PlatformAdmin |
| GET | `/pump-models` | List hydraulic models | All roles |
| GET | `/pump-models/{id}` | Read one hydraulic model | All roles |
| POST | `/pump-models/{id}/supersede` | Mark a model as superseded by a successor generation | PlatformAdmin |
| POST | `/pattern-assets` | Register casting tooling held at a foundry for one model | PlatformAdmin |
| GET | `/pattern-assets` | List casting patterns | All roles |
| GET | `/pattern-assets/{id}` | Read one pattern including its reconciled wear index | All roles |
| POST | `/pattern-assets/{id}/refurbishment-start` | Withdraw a worn pattern for refurbishment | PlatformAdmin |
| POST | `/pattern-assets/{id}/refurbishment-complete` | Return a refurbished pattern to service and restart its wear curve | PlatformAdmin |
| POST | `/pattern-assets/{id}/retire` | Retire tooling permanently | PlatformAdmin |
| POST | `/material-seal-configs` | Release a material and seal configuration for a model | PlatformAdmin |
| GET | `/material-seal-configs` | List material and seal configurations | All roles |
| GET | `/material-seal-configs/{id}` | Read one material and seal configuration | All roles |
| POST | `/duty-applications` | Open a customer enquiry carrying the guaranteed duty point and acceptance grade | ApplicationEngineer |
| GET | `/duty-applications` | List enquiries | All roles |
| GET | `/duty-applications/{id}` | Read one enquiry, whose version is the concurrency token for sizing | All roles |
| POST | `/selections` | Size a pump for an enquiry and gate the result against envelope, service and efficiency rules | ApplicationEngineer |
| GET | `/selections` | List selections | All roles |
| GET | `/selections/{id}` | Read one selection with every computed hydraulic value | All roles |
| POST | `/selections/{id}/propose` | Submit a selection for hydraulic approval, or re-submit one returned for review | ApplicationEngineer |
| POST | `/selections/{id}/revise` | Pull a proposed selection back to draft and discard the proposer identity | ApplicationEngineer |
| POST | `/selections/{id}/approve` | Approve a selection | HydraulicApprover |
| POST | `/selections/{id}/supersede` | Retire an approved selection and return the enquiry to open | ApplicationEngineer |
| POST | `/casting-lots` | Record a pour against a pattern at a foundry | FoundryPartner |
| GET | `/casting-lots` | List casting lots | All roles |
| GET | `/casting-lots/{id}` | Read one lot including the reconciled piece ledger | All roles |
| POST | `/casting-lots/{id}/inspect` | Record first-article or post-rework inspection of a lot | QualityInspector |
| POST | `/casting-lots/{id}/accept` | Accept an inspected lot for production use | QualityInspector |
| POST | `/casting-lots/{id}/rework-start` | Send a quarantined lot to weld rework | QualityInspector |
| POST | `/casting-lots/{id}/scrap-lot` | Write off a quarantined lot in full | QualityInspector |
| POST | `/casting-lots/{id}/defects` | Report a casting defect against a lot | FoundryPartner, QualityInspector |
| GET | `/casting-defects` | List casting defects | All roles |
| GET | `/casting-defects/{id}` | Read one casting defect | All roles |
| POST | `/casting-defects/{id}/disposition` | Apply an engineering disposition to a reported defect | QualityInspector |
| POST | `/casting-defects/{id}/revise-disposition` | Revise a scrap disposition to a weld repair | QualityInspector |
| POST | `/casting-defects/{id}/repair-verified` | Sign off a completed weld repair | QualityInspector |
| POST | `/build-orders` | Open a manufacturing order against an approved selection and an accepted lot | ProductionPlanner |
| GET | `/build-orders` | List manufacturing orders | All roles |
| GET | `/build-orders/{id}` | Read one manufacturing order including the recorded assembly measurements | All roles |
| POST | `/build-orders/{id}/assembly` | Record machining and assembly results | ProductionPlanner |
| POST | `/build-orders/{id}/rework-complete` | Sign off a rework loop after a failed performance test | ProductionPlanner |
| POST | `/build-orders/{id}/reassign-lot` | Re-bind a casting-short order to a different accepted lot | ProductionPlanner |
| POST | `/build-orders/{id}/kit-allocations/auto` | Reserve a repair kit chosen by the interchange selector | ProductionPlanner |
| POST | `/test-runs` | Open a performance test against an assembled unit | TestEngineer |
| GET | `/test-runs` | List performance tests | All roles |
| GET | `/test-runs/{id}` | Read one performance test with all three state dimensions | All roles |
| POST | `/test-runs/{id}/points` | Append one measured point to an open test run | TestEngineer |
| GET | `/test-points` | List measured points | All roles |
| GET | `/test-points/{id}` | Read one measured point | All roles |
| POST | `/test-runs/{id}/lock` | Freeze the measured point set | TestEngineer |
| POST | `/test-runs/{id}/evaluate` | Build the reported curve, interpolate the guarantee point and set both result dimensions | TestEngineer |
| POST | `/test-runs/{id}/certify` | Issue the certified test curve | TestEngineer |
| POST | `/test-runs/{id}/reopen` | Reopen an evaluated run for additional points | TestEngineer |
| POST | `/pump-packages` | Engineer a package around a tested unit: baseplate, motor and controls | ProductionPlanner |
| GET | `/pump-packages` | List packages | All roles |
| GET | `/pump-packages/{id}` | Read one package including the guarantee basis fixed at release | All roles |
| POST | `/pump-packages/{id}/release` | Release a package for shipment and fix its warranty guarantee basis | ProductionPlanner |
| POST | `/pump-packages/{id}/ship` | Ship a released package and start the warranty clock | ProductionPlanner |
| POST | `/pump-packages/{id}/release-hold` | Lift a casting-short hold once the order is re-bound to an accepted lot | ProductionPlanner |
| POST | `/repair-kits` | Catalogue a spare-parts repair kit with its generation coverage and support window | PlatformAdmin |
| GET | `/repair-kits` | List repair kits | All roles |
| GET | `/repair-kits/{id}` | Read one repair kit, whose version is the concurrency token for reservations | All roles |
| POST | `/repair-kits/{id}/receipts` | Receive units into kit stock | ProductionPlanner |
| POST | `/repair-kits/{id}/discontinue` | Withdraw a kit from the catalogue | PlatformAdmin |
| POST | `/kit-allocations` | Reserve units of an explicitly named repair kit against a build order | ProductionPlanner |
| GET | `/kit-allocations` | List kit allocations | All roles |
| GET | `/kit-allocations/{id}` | Read one kit allocation with its priced charge breakdown | All roles |
| POST | `/kit-allocations/{id}/issue` | Issue reserved units to the shop floor | ProductionPlanner |
| POST | `/kit-allocations/{id}/consume` | Book issued units as consumed | ProductionPlanner |
| POST | `/kit-allocations/{id}/release` | Release a reservation and return the units to stock | ProductionPlanner |
| POST | `/warranty-claims` | Raise a field-performance warranty claim against a shipped package | ApplicationEngineer |
| GET | `/warranty-claims` | List warranty claims | All roles |
| GET | `/warranty-claims/{id}` | Read one warranty claim with its determination and settlement breakdown | All roles |
| POST | `/warranty-claims/{id}/begin-adjudication` | Take a submitted claim into adjudication | WarrantyAdjudicator |
| POST | `/warranty-claims/{id}/request-info` | Return a claim to the field for more information | WarrantyAdjudicator |
| POST | `/warranty-claims/{id}/resume-adjudication` | Resume adjudication after the requested information arrives | WarrantyAdjudicator |
| POST | `/warranty-claims/{id}/adjudicate` | Determine liability against the package's guarantee basis | WarrantyAdjudicator |
| POST | `/warranty-claims/{id}/settle` | Settle a manufacturing-defect claim | WarrantyAdjudicator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCED_RESOURCE_NOT_FOUND` | 404 |
| `ERR_FOUNDRY_SCOPE_VIOLATION` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_ADJUDICATOR_CONFLICT` | 409 |
| `ERR_STALE_DUTY_APPLICATION_VERSION` | 412 |
| `ERR_STALE_REPAIR_KIT_VERSION` | 412 |
| `ERR_ZERO_QUANTITY` | 422 |
| `ERR_DUPLICATE_CODE` | 409 |
| `ERR_AFFECTED_QTY_EXCEEDS_LEDGER` | 422 |
| `ERR_DUTY_APPLICATION_NOT_OPEN` | 409 |
| `ERR_SELECTION_INVALID_STATE` | 409 |
| `ERR_CASTING_LOT_INVALID_STATE` | 409 |
| `ERR_DEFECT_INVALID_STATE` | 409 |
| `ERR_BUILD_ORDER_INVALID_STATE` | 409 |
| `ERR_TEST_RUN_INVALID_STATE` | 409 |
| `ERR_PACKAGE_INVALID_STATE` | 409 |
| `ERR_ALLOCATION_INVALID_STATE` | 409 |
| `ERR_CLAIM_INVALID_STATE` | 409 |
| `ERR_PATTERN_INVALID_STATE` | 409 |
| `ERR_REPAIR_KIT_DISCONTINUED` | 409 |
| `ERR_FOUNDRY_SUSPENDED` | 409 |
| `ERR_MODEL_NOT_ORDERABLE` | 409 |
| `ERR_PATTERN_NOT_QUALIFIED` | 409 |
| `ERR_CASTING_LOT_NOT_ACCEPTED` | 409 |
| `ERR_TEST_RUN_NOT_CERTIFIED` | 409 |
| `ERR_SELECTION_NOT_APPROVED` | 409 |
| `ERR_BUILD_ORDER_NOT_ASSEMBLED` | 409 |
| `ERR_BUILD_ORDER_NOT_TESTED` | 409 |
| `ERR_PACKAGE_NOT_SHIPPED` | 409 |
| `ERR_CONFIG_MODEL_MISMATCH` | 422 |
| `ERR_LOT_MODEL_MISMATCH` | 422 |
| `ERR_ALLOY_NOT_APPROVED` | 422 |
| `ERR_TEST_RUN_BUILD_MISMATCH` | 422 |
| `ERR_SUCCESSOR_MODEL_INVALID` | 422 |
| `ERR_KIT_GROUP_MISMATCH` | 422 |
| `ERR_TEMPERATURE_LIMIT_EXCEEDED` | 422 |
| `ERR_CHLORIDE_LIMIT_EXCEEDED` | 422 |
| `ERR_SOLIDS_LIMIT_EXCEEDED` | 422 |
| `ERR_VISCOSITY_LIMIT_EXCEEDED` | 422 |
| `ERR_SERVICE_CLASS_MISMATCH` | 422 |
| `ERR_DUTY_FLOW_ABOVE_MAX` | 422 |
| `ERR_TRIM_BELOW_MINIMUM` | 422 |
| `ERR_DUTY_POINT_ABOVE_ENVELOPE` | 422 |
| `ERR_NPSH_MARGIN_INSUFFICIENT` | 409 |
| `ERR_UNBALANCE_EXCEEDS_ALLOWANCE` | 422 |
| `ERR_CLEARANCE_OUT_OF_BAND` | 422 |
| `ERR_FLUSH_PLAN_MISMATCH` | 422 |
| `ERR_INSUFFICIENT_TEST_POINTS` | 409 |
| `ERR_NPSH_TEST_POINT_MISSING` | 409 |
| `ERR_GUARANTEE_FLOW_NOT_BRACKETED` | 409 |
| `ERR_HYDRAULIC_OUT_OF_TOLERANCE` | 409 |
| `ERR_NPSH_NOT_VERIFIED` | 409 |
| `ERR_PATTERN_WINDOW_CONFLICT` | 409 |
| `ERR_FOUNDRY_POUR_CAPACITY_EXCEEDED` | 409 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_REWORK_LIMIT_EXCEEDED` | 409 |
| `ERR_KIT_GENERATION_NOT_COVERED` | 422 |
| `ERR_KIT_SUPPORT_WINDOW_EXPIRED` | 422 |
| `ERR_KIT_STOCK_INSUFFICIENT` | 409 |
| `ERR_NO_INTERCHANGEABLE_KIT` | 422 |
| `ERR_WARRANTY_EXPIRED` | 422 |
| `ERR_EMPTY_CLAIM_LINES` | 422 |
| `ERR_OPEN_DEFECTS_PRESENT` | 409 |
| `ERR_NO_ACCEPTABLE_CASTINGS` | 409 |
| `ERR_EFFICIENCY_TARGET_NOT_MET` | 422 |
| `ERR_MOTOR_UNDERSIZED` | 422 |
