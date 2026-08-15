# Tea Blending Operations API — Product Requirements Document

## 1. Introduction

A tea blending and packing operation lives or dies by consistency: the same recipe must taste the same whether the leaf came from this spring's Assam lot or last autumn's Kenyan auction purchase, and every pack leaving the line must be traceable back to certified gardens, laboratory results, and the exact kilograms drawn from each lot. Behind that consistency sits a dense web of controls — sensory grading by trained tasters, pesticide-residue screening with a retest loop, moisture gates that guard shelf life, organic and fair-trade mass-balance ledgers, allergen-aware line scheduling, and private-label minimums that shape what may be packed for whom.

This document specifies the Tea Blending Operations API, the system of record for that operation. It covers the full production chain: registering suppliers and intake leaf lots, grading and laboratory clearance, recipe definition, batch blending and flavoring under strict segregation of duties, certification volume accounting, packaging-line scheduling, and private-label contract fulfillment. All endpoints are mounted under the `/tea-ops` prefix and are governed by the role-based access rules, state machines, and calculation contracts defined below.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, formats, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming their operational capacity. The system recognizes exactly nine roles: `ProcurementLead` (supplier registry and leaf-lot intake), `SensoryGrader` (sensory grading), `QALabAnalyst` (pesticide residue testing), `QAManager` (release and recall of lots and batches), `BlendMaster` (flavorings, recipes, batches, blending and flavoring application), `ProductionPlanner` (packaging lines and production runs), `AccountManager` (private-label contracts), `CertificationOfficer` (organic and fair-trade certificate grants), and `PlatformAdmin` (operations-only control of the logical clock). A request with a missing or invalid header, or whose role is not one of these nine, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is valid but not among the endpoint's authorized roles is rejected with `ERR_FORBIDDEN` (HTTP 403). All read endpoints are open to every one of the nine roles.

For each of the nine roles — `ProcurementLead`, `SensoryGrader`, `QALabAnalyst`, `QAManager`, `BlendMaster`, `ProductionPlanner`, `AccountManager`, `CertificationOfficer`, and `PlatformAdmin` — `X-User-ID` is an opaque operator identifier that is never the `id` of any persisted entity. The server records it on the resources an operator creates or advances — as `registered_by_user_id` on a leaf lot, `grader_user_id` on a grade assessment, `submitted_by_user_id` on a residue test, `blended_by_user_id` on a blend batch, or `applied_by_user_id` on a flavoring application — and those stamps anchor the segregation-of-duties comparisons of §2.9, but `X-User-ID` itself is never compared to any entity's `id`.

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

Requests that match no route are rejected with `ERR_NOT_FOUND` (HTTP 404); a known path addressed with an unsupported method is rejected with the `ERR_NOT_FOUND` error identifier at HTTP 405; and an unexpected server failure surfaces as `ERR_INTERNAL` (HTTP 500) — all three in the same error envelope.

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. A non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400); out-of-range values are clamped rather than rejected — a `limit` below 1 is treated as 1, a `limit` above 100 is treated as 100, and an `offset` below 0 is treated as 0 — and the `meta` fields report the effective clamped values.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order; ties on `created_at` are broken by creation (insertion) order, earliest first.

Paginated list responses carry four fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`. `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. Common Resource Properties

Ten primary resources — Supplier, LeafLot, Flavoring, BlendRecipe, BlendBatch, BatchLotAllocation, PackagingLine, ProductionRun, PrivateLabelContract, and CertificateGrant — share a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp, again with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter that starts at 1 when the resource is created and increments by one on every mutation — including mutations caused by the cascades of §2.8, which touch each affected entity in its own right.

Three record-type resources — GradeAssessment, ResidueTest, and FlavoringApplication — are immutable once created. They carry only `id` and `created_at`; both `updated_at` and `version` are absent from them.

Every entity also exposes a `status` field whose enumerated values are introduced throughout §3 alongside the workflows that move between them.

### 2.5. The Logical Clock, Calendar Dates, and the Certificate Expiry Sweep

Time inside the system is logical, never wall-clock. A `PlatformAdmin` advances the clock through an operations-only capability that accepts a target instant in the `to_iso8601` field and answers with the new `current_utc`. Any parseable ISO 8601 instant is accepted — a reading without an explicit offset is treated as UTC — and the target is not required to be later than the current reading; the clock is simply set to the given instant. Before any such call, the clock reads exactly `2026-08-01T00:00:00Z`, and the server must never fall back to wall-clock time. The logical clock decides production-run window membership, stamps the `started_at` and `completed_at` fields of runs, supplies the current date for certificate-validity checks at batch release and certificate reinstatement, and provides the completion date used in shelf-life harvest-age arithmetic.

Setting the clock also triggers a certificate expiry sweep: every certificate grant whose `valid_until` date is earlier than the new current date — whether currently `ACTIVE` or `SUSPENDED` — transitions to `EXPIRED`.

Three fields are calendar dates rather than datetimes: a lot's `harvest_date` and a certificate's `valid_from` and `valid_until` are written as YYYY-MM-DD with UTC date semantics. Certificate validity is a closed interval that includes both boundary dates.

### 2.6. Precision, Rounding, and Comparison Conventions

One rounding rule governs the whole API: round half up. Sensory composite scores are computed and stored at one decimal place. Kilogram quantities — the flavoring reservation, per-component requirements, allocation yields, and certificate volumes — are computed at three decimal places, and any rule described in this document as requiring an exact kilogram match compares the two sides at three-decimal precision. Money is integer cents at zero decimal places: per-line amounts are rounded to whole cents first and only then summed — a sum is never rounded after the fact. Shelf-life figures are whole days, and where a formula prescribes a ceiling step it is applied exactly where the formula states, no earlier and no later. Moisture percentages are plain decimal numbers compared exactly against the thresholds quoted in the text.

### 2.7. Optimistic Concurrency Control

Two write endpoints carry a mandatory optimistic-concurrency field, and the field is not optional on either. A request to `POST /tea-ops/batches/{id}/allocations` must include `expected_batch_version`, holding the batch `version` the client last observed; if the batch's current `version` differs — because another writer has since mutated the batch, for example by adding an allocation of their own — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). A request to `PUT /tea-ops/recipes/{id}` must likewise include `expected_recipe_version`, and a mismatch with the recipe's current `version` is rejected with the same `ERR_STALE_VERSION` (HTTP 412), so two edits based on the same observed version cannot both succeed. On both endpoints the field must carry an integer: a missing or non-integer value fails field-shape validation with `ERR_INVALID_REQUEST` (HTTP 400), while a well-formed but stale integer fails the concurrency check with `ERR_STALE_VERSION`. Endpoints not named here do not accept a version field.

### 2.8. Cascading Hold Propagation

Holds spread through the operation along three fixed links. Link 1 is the lot hold: suspending a supplier moves every one of its lots in `GRADED`, `LAB_SUBMITTED`, or `RELEASED` to `ON_HOLD`, while lots in `REGISTERED`, `REJECTED`, or `DEPLETED` are left untouched. A lot can also enter `ON_HOLD` on its own — through a soft-fail residue verdict or a QA recall — and in those cases the cascade enters at link 2. Link 2 is the batch hold: every blend batch that holds an `ACTIVE` allocation from a lot that has just gone `ON_HOLD`, and that itself sits in `RECIPE_LOCKED`, `ALLOCATED`, `BLENDED`, `FLAVORED`, `QC_REVIEW`, or `RELEASED`, transitions to `ON_HOLD`. Link 3 is the run cancellation: every production run still `SCHEDULED` that references a batch which has just gone `ON_HOLD` transitions to `CANCELLED`. Certificate suspension enters the cascade directly at link 2 with its own batch selection rule, described in §3.6. Every entity touched by a cascade is genuinely mutated: its `updated_at` refreshes and its `version` increments.

Reinstatement is never a bulk undo. Reinstating a supplier or a certificate performs no automatic un-hold: a held lot leaves `ON_HOLD` only through a fresh residue test that passes, and a held batch re-enters quality review only through the rework submission path described in §3.5.

### 2.9. Segregation of Duties

Three upstream/downstream steps may never be performed by the same operator. The grader of a lot must differ from the operator who registered it, recorded as the lot's `registered_by_user_id`. The QA manager releasing a lot must differ from the analyst recorded as `submitted_by_user_id` on that lot's latest residue test. The QA manager releasing a batch must differ from the blend master recorded as the batch's `blended_by_user_id`. A violation of any of the three is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

### 2.10. Request Validation Order

Every request is checked against the following sequence, and the first failure encountered wins — later checks never mask an earlier rejection:

1. Authentication: both headers present and the role among the nine declared roles, else `ERR_UNAUTHENTICATED`.
2. Authorization: the acting role is listed for the endpoint, else `ERR_FORBIDDEN`.
3. Existence: path identifiers resolve left to right, then body foreign keys resolve, else `ERR_NOT_FOUND`.
4. Concurrency: where §2.7 applies, the expected-version field matches the parent's current `version`, else `ERR_STALE_VERSION`.
5. Terminal guard: the target entity is not in a terminal state for this action, else `ERR_ALREADY_TERMINAL`.
6. Endpoint state preconditions: the specific state the endpoint demands, reported with the endpoint-specific code where one exists — `ERR_LOT_NOT_RELEASABLE`, `ERR_SUPPLIER_SUSPENDED`, `ERR_LOT_NOT_RELEASED`, `ERR_RECIPE_NOT_ACTIVE`, `ERR_BATCH_NOT_RELEASABLE`, `ERR_BATCH_NOT_FLAVORABLE`, `ERR_FLAVORING_REQUIRED`, `ERR_LINE_NOT_ACTIVE`, `ERR_CONTRACT_NOT_ACTIVE`, or `ERR_RUN_OUTSIDE_WINDOW` — and otherwise with the generic `ERR_INVALID_STATE`.
7. Segregation of duties, per §2.9, else `ERR_SEGREGATION_OF_DUTIES`.
8. Business safety gates — the moisture limits, the organic-flavoring rule, and certification presence and volume — reported as `ERR_MOISTURE_OUT_OF_RANGE`, `ERR_SYNTHETIC_ON_ORGANIC`, `ERR_CERT_NOT_ACTIVE`, or `ERR_CERT_VOLUME_EXHAUSTED`.
9. Temporal checks — window validity, line overlap, the allergen changeover buffer, and certificate overlap — reported as `ERR_INVALID_WINDOW`, `ERR_LINE_WINDOW_CONFLICT`, `ERR_ALLERGEN_CHANGEOVER_BUFFER`, or `ERR_CERT_WINDOW_CONFLICT`.
10. Business constraints — recipe composition, allocation matching and fill, flavoring identity and dose, contract-recipe agreement, and line format — reported as `ERR_RECIPE_COMPOSITION_INVALID`, `ERR_ALLOCATION_TYPE_MISMATCH`, `ERR_ALLOCATION_GRADE_TOO_LOW`, `ERR_LOT_WEIGHT_EXCEEDED`, `ERR_DUPLICATE_LOT_ALLOCATION`, `ERR_FILL_INCOMPLETE`, `ERR_SINGLE_LOT_DOMINANCE`, `ERR_FLAVORING_MISMATCH`, `ERR_FLAVORING_DOSE_MISMATCH`, `ERR_CONTRACT_RECIPE_MISMATCH`, or `ERR_LINE_FORMAT_MISMATCH`.
11. Flavoring liveness at recipe activation and at flavoring application, else `ERR_FLAVORING_NOT_ACTIVE`.
12. Private-label run minimums at run scheduling and completion, else `ERR_PRIVATE_LABEL_MINIMUM_UNMET`.
13. Field shape: required fields present, enums in range, scores within 0 to 100, weights and quantities strictly positive, residue measurements non-negative — failures reported as `ERR_INVALID_REQUEST` (HTTP 400). Although listed last, a structurally malformed payload is rejected before any business rule of steps 8 through 12 executes — but never before the authentication, authorization, existence, concurrency, and state checks of steps 1 through 7 have passed.

### 2.11. Resource Addressing and Existence Checks

Resources are addressed flatly by `id`, with sub-collections nested under their owner — grade assessments, residue tests, and allocations under a leaf lot; allocations and flavoring applications under a batch; flavoring applications under a flavoring. When a path contains several identifiers, existence is validated left to right, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource. After the path is validated, foreign keys supplied in the request body — `supplier_id`, `recipe_id`, `lot_id`, `line_id`, `batch_id`, `contract_id`, and `flavoring_id` — are resolved in the same manner and produce the same error when they point at nothing.

## 3. Business Logic & Workflows

### 3.1. Supplier Registry and Leaf-Lot Intake

A `ProcurementLead` opens the supply chain by registering each supplier under its `name` and `origin_region`; new suppliers start `ACTIVE`. Intake continues with the leaf lots themselves. Each lot record carries the sourcing `supplier_id`, a `leaf_type` of `BLACK`, `GREEN`, `WHITE`, `OOLONG`, or `HERBAL`, the `harvest_date`, the gross received `weight_kg` (strictly positive), the contracted `cost_per_kg_cents` (a non-negative integer), and the intake `moisture_pct` (greater than zero and at most one hundred). Registration stamps `registered_by_user_id` from the calling header, initializes `remaining_weight_kg` to the full `weight_kg`, sets both `composite_grade` and `latest_residue_verdict` to `NONE`, and places the lot in `REGISTERED`. From then on `remaining_weight_kg` is a derived figure: the gross weight minus the kilograms committed across the lot's `ACTIVE` allocations.

Suspending a supplier — a `ProcurementLead` decision available while the supplier is `ACTIVE` — moves it to `SUSPENDED` and fires the full three-link cascade of §2.8: its graded, lab-submitted, and released lots go `ON_HOLD`, batches drawing on those lots follow, and their scheduled runs are cancelled. Reinstatement, likewise restricted to `ProcurementLead` and available only from `SUSPENDED`, returns the supplier to `ACTIVE` but un-holds nothing by itself. Suppliers have no terminal state.

### 3.2. Sensory Grading and the Residue Testing Loop

Grading comes first. A `SensoryGrader` scores a `REGISTERED` lot on `aroma_score`, `briskness_score`, and `appearance_score`, each an integer from 0 to 100 inclusive. The composite score weighs aroma at 0.40, briskness at 0.35, and appearance at 0.25, sums the three weighted terms, and rounds half-up to one decimal place; the result is stored as `composite_score` on the persisted assessment, which also records the lot's `lot_id` and the grader's `grader_user_id`. Grade thresholds are inclusive: a composite of at least 85.0 earns `A`, at least 70.0 earns `B`, at least 55.0 earns `C`, and anything below 55.0 is a `REJECT`. The lot adopts the assessment's `composite_grade` as its own: a grade of `A`, `B`, or `C` moves it from `REGISTERED` to `GRADED`, while a `REJECT` grade moves it straight to `REJECTED`. Segregation of duties applies at this door — an operator may not grade a lot they registered themselves, and the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`.

Laboratory screening follows. A `QALabAnalyst` files a residue test with the `lab_name`, the `measured_residue_ppm` (zero or greater), and the `test_method`; the system stamps `submitted_by_user_id` and assigns `test_round` as the 1-based chronological count of residue tests filed against that lot. A residue test is accepted only while the lot is `GRADED` or `ON_HOLD`; filing one against a lot in any other non-terminal state is rejected with `ERR_INVALID_STATE`. The verdict compares the single measurement against the 0.50 ppm residue limit: at most 0.50 ppm, inclusive, is a `PASS`; strictly more than 1.00 ppm — twice the limit — is a `FAIL_HARD`; anything in between is a `FAIL_SOFT`. The boundaries behave exactly as written: a reading of 0.50 passes, 1.00 is a soft fail, and 1.01 is a hard fail. Whatever the outcome, the lot's `latest_residue_verdict` always reflects the newest test's `verdict`.

From `GRADED`, a `PASS` advances the lot to `LAB_SUBMITTED`; a `FAIL_SOFT` moves it to `ON_HOLD` and fires cascade links 2 and 3 — batches holding its `ACTIVE` allocations go `ON_HOLD`, and their scheduled runs are cancelled; a `FAIL_HARD` rejects the lot outright into `REJECTED`. From `ON_HOLD` the loop repeats: a passing retest moves the lot to `LAB_SUBMITTED` with the incremented `test_round` recorded, a soft-failing retest leaves the lot `ON_HOLD`, and a hard-failing retest ends it in `REJECTED`.

Release is a separate, gated decision by a `QAManager`. The lot must be `LAB_SUBMITTED` with a latest verdict of `PASS` — anything else is rejected with `ERR_LOT_NOT_RELEASABLE`. Its supplier must be `ACTIVE`; a suspended supplier blocks release with `ERR_SUPPLIER_SUSPENDED`. Its intake `moisture_pct` must be at most 7.0 percent; a wetter lot fails the gate with `ERR_MOISTURE_OUT_OF_RANGE`. And the releaser must not be the analyst who submitted the lot's latest residue test, on pain of `ERR_SEGREGATION_OF_DUTIES`. A released lot becomes allocatable to batches. Should a problem surface after release, a `QAManager` recall moves a `RELEASED` lot back to `ON_HOLD` and again fires cascade links 2 and 3.

Two lot transitions belong to the system alone: a `RELEASED` lot whose `remaining_weight_kg` reaches exactly zero after an allocation becomes `DEPLETED`, and a `DEPLETED` lot whose remaining weight climbs back above zero when a cancellation releases allocations returns to `RELEASED`. `REJECTED` and `DEPLETED` are terminal for client-driven actions — acting on either is rejected with `ERR_ALREADY_TERMINAL` — and only the system's own restoration transition ever leads out of `DEPLETED`.

### 3.3. Flavorings and Blend Recipe Composition

`BlendMaster`s maintain the flavoring catalog. Each flavoring is registered with a `name`, an `allergen_tags` list drawn from `TREE_NUT`, `SOY`, `GLUTEN`, and `LACTOSE` (an empty list declares the agent allergen-free), a `natural_certified` flag marking certification as natural, and a `cost_per_kg_cents` of zero or more. Flavorings start `ACTIVE`. Retiring one moves it to `RETIRED` — a terminal state — which leaves existing flavoring applications untouched but bars all future use: recipe activation or flavoring application referencing a retired flavoring fails with `ERR_FLAVORING_NOT_ACTIVE`.

A blend recipe captures a `name`, a `certification_target` of `CONVENTIONAL`, `ORGANIC`, or `FAIR_TRADE`, a `pack_format` of `TEA_BAG` or `LOOSE_PACK`, and a `components` array in which every entry names a `leaf_type`, a `min_grade` of `A`, `B`, or `C`, and a percentage share `pct`. Grade ordering is `A` above `B` above `C`, and a lot satisfies a component's `min_grade` when its own `composite_grade` ranks at or above that minimum. An optional `flavoring_id` — null for unflavored recipes, its default — plus a `flavoring_pct` (default zero) reserve a share of the total batch weight for flavoring. Composition is exact: the component `pct` values plus the `flavoring_pct` must sum to exactly 100.00, and empty or malformed component arrays are invalid. Violations surface as `ERR_RECIPE_COMPOSITION_INVALID`, enforced when the recipe is created and checked again at activation. A missing `components` field is treated as a malformed array and draws the same `ERR_RECIPE_COMPOSITION_INVALID`, as does a negative `flavoring_pct`. New recipes start in `DRAFT`.

While a recipe remains `DRAFT`, a `BlendMaster` may revise it — `name`, `certification_target`, `pack_format`, `components`, `flavoring_id`, and `flavoring_pct` are all mutable — but the revision request must carry `expected_recipe_version` per §2.7, and each accepted revision increments the recipe's `version` by one. A revision may carry any subset of the mutable fields; fields omitted from the request are left unchanged, and the exact-100.00 composition sum is not re-evaluated at revision time — only component entry shape is — with the sum checked again at activation. Attempting to revise or activate a recipe that has left `DRAFT` is rejected with `ERR_INVALID_STATE`; any action on a `RETIRED` recipe meets `ERR_ALREADY_TERMINAL`.

Activation moves a `DRAFT` recipe to `ACTIVE`. Beyond the composition sum, activation confirms that `flavoring_id` is either null or references a currently `ACTIVE` flavoring — a retired reference fails with `ERR_FLAVORING_NOT_ACTIVE`. Retirement moves an `ACTIVE` recipe to `RETIRED` and cascades: every batch of this recipe still in `DRAFT` or `RECIPE_LOCKED` is cancelled, and each such cancellation releases the batch's allocations — the `ACTIVE` allocations flip to `RELEASED`, the drawn kilograms are credited back to each lot's `remaining_weight_kg`, and a `DEPLETED` lot restored above zero returns to `RELEASED`.

### 3.4. Building a Batch: Recipe Lock and Lot Allocation

A `BlendMaster` creates a batch by naming an `ACTIVE` recipe's `recipe_id` and a strictly positive `target_weight_kg` covering leaf and flavoring combined; referencing a recipe that is not `ACTIVE` is rejected with `ERR_RECIPE_NOT_ACTIVE`. The new batch starts in `DRAFT`, immediately snapshots the recipe's `pack_format` onto itself, begins with an empty `allergen_tags` list, and opens with an empty `cert_charges` ledger. Every other derived field — `recipe_version`, `required_components`, `flavoring_kg`, `measured_moisture_pct`, `yield_kg`, `blended_by_user_id`, `provisional_cost_cents`, `final_cost_cents`, and `actual_weight_kg` — is null until the workflow step that sets it.

Locking the recipe pins the batch to the recipe exactly as it stands at that moment. The batch must be in `DRAFT`, and the referenced recipe must still be `ACTIVE` (again `ERR_RECIPE_NOT_ACTIVE`). The lock moves the batch to `RECIPE_LOCKED`, pins `recipe_version` to the recipe's current `version`, and explodes the recipe into concrete requirements. The evaluation order is pinned: the flavoring reservation comes first — `flavoring_kg` is the `target_weight_kg` multiplied by the recipe's `flavoring_pct` and divided by 100, rounded half-up to three decimal places — and only then is the leaf pool computed as the `target_weight_kg` minus the reserved `flavoring_kg`. Each component's `required_kg` is that leaf pool multiplied by the component's `pct` and divided by the sum of all component `pct` values, again rounded half-up to three decimal places, and the resulting triples of leaf type, minimum grade, and required kilograms are frozen into `required_components`. Computing leaf shares against the full target instead of the flavoring-reduced pool would over-allocate leaf by exactly the flavoring amount; the pinned order is the contract.

With requirements pinned, the `BlendMaster` draws leaf lot by lot. Each allocation request carries the `lot_id`, the `allocated_kg` to draw, and `expected_batch_version` per §2.7 — a stale batch view is rejected with `ERR_STALE_VERSION`. Allocations are created against the batch in the window between recipe lock and allocation finalization, and each draw must clear four checks. The lot must currently be `RELEASED`; any other lot status is `ERR_LOT_NOT_RELEASED`. The draw must be strictly positive and no greater than the lot's `remaining_weight_kg`; overdraws fail with `ERR_LOT_WEIGHT_EXCEEDED`. The lot's `leaf_type` must match some component of the recipe, else `ERR_ALLOCATION_TYPE_MISMATCH`. And the lot's `composite_grade` must satisfy the matched component's `min_grade`, else `ERR_ALLOCATION_GRADE_TOO_LOW`; when several components share the lot's `leaf_type`, the grade check is satisfied if the lot's grade meets the `min_grade` of any one of them. Nor may the same lot be drawn twice into one batch: a second `ACTIVE` allocation against an already-allocated lot is rejected with `ERR_DUPLICATE_LOT_ALLOCATION`. Every accepted allocation persists with its `batch_id`, starts `ACTIVE`, books its `line_cost_cents` as the allocated kilograms times the lot's `cost_per_kg_cents` rounded half-up to whole cents, debits the lot's `remaining_weight_kg` by the drawn amount — auto-depleting the lot to `DEPLETED` when the remainder hits exactly zero — and increments the batch's `version` by one.

Finalizing the allocation is the point of no return for sourcing. For every required component, the kilograms covered by `ACTIVE` allocations drawn from lots of the component's leaf type whose grade meets the `min_grade` must equal the component's `required_kg` exactly, compared at three-decimal precision; any shortfall or overshoot is rejected with `ERR_FILL_INCOMPLETE`. Blend consistency adds a dominance ceiling: for any component whose `required_kg` exceeds 25.0 kg, no single lot may supply more than 70 percent of that component — a share strictly above 0.70 violates the rule, while a share of exactly 0.70 is permitted — and a breach is rejected with `ERR_SINGLE_LOT_DOMINANCE`. Every allocated lot must at that moment hold a status of `RELEASED` or `DEPLETED`. A successful finalization moves the batch from `RECIPE_LOCKED` to `ALLOCATED` and books `provisional_cost_cents`: the sum, over the batch's `ACTIVE` allocation lines, of each line's allocated kilograms multiplied by its lot's cost per kilogram, with every line rounded half-up to whole cents before the lines are summed. The provisional figure is leaf cost only — no flavoring, no waste surcharge.

### 3.5. Blending, Flavoring Application, and Quality Release

Blending records what the dryer and the blender actually achieved. From `ALLOCATED`, the `BlendMaster` runs the blend and reports the post-blend `measured_moisture_pct` — which must be greater than zero and at most one hundred, else `ERR_INVALID_REQUEST`; the system stamps `blended_by_user_id` from the calling header, moves the batch to `BLENDED`, and computes `yield_kg`. The yield calculation walks the batch's `ACTIVE` allocation lines one by one, joining each to its lot's intake `moisture_pct`. A lot whose moisture exceeds the 5.0 percent target contributes its allocated kilograms multiplied by a shrink factor: one minus the ratio of the lot's excess over target to the headroom below saturation — that is, the lot's `moisture_pct` minus 5.0, divided by 100 minus 5.0, subtracted from one — with the line result rounded half-up to three decimal places. A lot at or below the 5.0 percent target contributes its full allocated kilograms unchanged. The batch's `yield_kg` is the sum of these already-rounded line yields, never a rounding applied to the sum.

Flavoring is a guarded step. When the recipe names a flavoring, the `BlendMaster` applies it to the `BLENDED` batch; attempting the step when the batch is not `BLENDED`, or under a recipe with no flavoring, is rejected with `ERR_BATCH_NOT_FLAVORABLE`. The request's `flavoring_id` must equal the recipe's own flavoring reference, else `ERR_FLAVORING_MISMATCH`. The flavoring must still be `ACTIVE`, else `ERR_FLAVORING_NOT_ACTIVE`. The `applied_kg` must equal the batch's computed `flavoring_kg` exactly at three-decimal precision, else `ERR_FLAVORING_DOSE_MISMATCH`. And when the recipe's `certification_target` is `ORGANIC`, only a flavoring whose `natural_certified` flag is true may be applied — a synthetic agent on an organic batch is rejected with `ERR_SYNTHETIC_ON_ORGANIC`. A successful application persists a flavoring application stamped with `applied_by_user_id`, books `flavoring_cost_cents` as the applied kilograms multiplied by the flavoring's `cost_per_kg_cents` rounded half-up to whole cents, copies the flavoring's `allergen_tags` onto the batch, and moves the batch to `FLAVORED`.

Quality submission offers exactly three doors into `QC_REVIEW`. An unflavored batch enters from `BLENDED` — but if the recipe names a flavoring, submitting straight from `BLENDED` is rejected with `ERR_FLAVORING_REQUIRED`, because the flavoring must be applied first. A flavored batch enters from `FLAVORED`, and exactly one flavoring application must exist for it. A held batch re-enters from `ON_HOLD` through the rework loop, which requires every lot referenced by the batch's `ACTIVE` allocations to be back in `RELEASED` or `DEPLETED`, and — when the recipe is flavored — exactly one flavoring application on record for the batch.

Release belongs to the `QAManager` and carries the operation's heaviest gates. The batch must sit in `QC_REVIEW`; a release attempted from any other state is `ERR_BATCH_NOT_RELEASABLE`. Its `measured_moisture_pct` must be at most 7.0 percent, else `ERR_MOISTURE_OUT_OF_RANGE`. The releaser must not be the operator who blended the batch, else `ERR_SEGREGATION_OF_DUTIES`. For recipes whose `certification_target` is `ORGANIC` or `FAIR_TRADE`, the certification chain is then audited supplier by supplier: every supplier contributing `ACTIVE` allocations to the batch must hold a certificate grant whose `cert_type` matches the recipe's target, whose status is `ACTIVE`, and whose validity interval contains the current logical-clock date — on or after `valid_from` and on or before `valid_until` — or the release fails with `ERR_CERT_NOT_ACTIVE`; and each such grant's remaining volume, its `total_volume_kg` minus its `consumed_volume_kg`, must be at least the kilograms that supplier contributes to the batch, or the release fails with `ERR_CERT_VOLUME_EXHAUSTED`. `CONVENTIONAL` recipes skip the chain audit entirely.

A first release settles the books. The batch's `cert_charges` are computed per the volume ledger of §3.6, and each charged grant's `consumed_volume_kg` rises by its charged amount; this charge happens only on the batch's first transition into `RELEASED`, never on a later re-release. The `final_cost_cents` extend the provisional figure: the `flavoring_cost_cents` across the batch's flavoring applications are added (zero when unflavored), a waste surcharge of two percent is computed on the combined leaf-and-flavoring subtotal and rounded half-up to whole cents, and the final cost is the sum of those three terms — given identical inputs, strictly larger than the provisional figure whenever flavoring cost or waste is nonzero. The batch's `actual_weight_kg` is set to its `yield_kg` plus its `flavoring_kg`, and the batch becomes `RELEASED`.

Two exits unwind work. Cancelling is a `BlendMaster` prerogative available from `DRAFT`, `RECIPE_LOCKED`, `ALLOCATED`, `BLENDED`, `FLAVORED`, `QC_REVIEW`, or `ON_HOLD`, and it moves the batch to `CANCELLED`. From `RECIPE_LOCKED` onward the cancellation releases the batch's sourcing: every `ACTIVE` allocation flips to `RELEASED`, each lot's `remaining_weight_kg` is credited back by the drawn `allocated_kg`, and a `DEPLETED` lot whose restored weight exceeds zero returns to `RELEASED`. A batch cancelled from `DRAFT` has no allocations to compensate. Recall is the `QAManager`'s post-release unwind: a `RELEASED` batch moves to `RECALLED`, every charge recorded in its `cert_charges` is returned to the corresponding grant and the `cert_charges` ledger is cleared, and every still-`SCHEDULED` run booked for the batch is cancelled — runs already `IN_PROGRESS` are left untouched. Both `CANCELLED` and `RECALLED` are terminal; any further action on such a batch meets `ERR_ALREADY_TERMINAL`.

### 3.6. Certification Chain-of-Custody and the Volume Ledger

A `CertificationOfficer` registers each certificate grant with its `supplier_id`, a `cert_type` of `ORGANIC` or `FAIR_TRADE`, a strictly positive `total_volume_kg` of certified mass-balance volume, and the `valid_from` and `valid_until` bounds of its closed validity interval. A grant whose start is not strictly before its end is rejected with `ERR_INVALID_WINDOW`. New grants start `ACTIVE` with `consumed_volume_kg` at zero. One supplier may hold several grants, but their intervals may not collide: a new grant whose closed interval overlaps — shared boundary dates count as overlap — an existing `ACTIVE` or `SUSPENDED` grant of the same `supplier_id` and `cert_type` is rejected with `ERR_CERT_WINDOW_CONFLICT`.

Suspending a grant — available from `ACTIVE` — moves it to `SUSPENDED` and fires its own variant of the §2.8 cascade, entering at link 2: every batch whose recipe's `certification_target` equals the grant's `cert_type`, which holds an `ACTIVE` allocation from a lot of the grant's supplier, and which sits in `RECIPE_LOCKED`, `ALLOCATED`, `BLENDED`, `FLAVORED`, `QC_REVIEW`, or `RELEASED`, moves to `ON_HOLD`, and every still-`SCHEDULED` run referencing such a batch is cancelled. Reinstatement returns a `SUSPENDED` grant to `ACTIVE`, but only while the grant's `valid_until` is on or after the current logical-clock date, and — as with suppliers — it un-holds nothing by itself; affected batches find their way back through the rework door of §3.5. Expiry is the clock's business: per §2.5, whenever the logical clock advances past a grant's `valid_until`, an `ACTIVE` or `SUSPENDED` grant becomes `EXPIRED`, a terminal state on which further actions meet `ERR_ALREADY_TERMINAL`.

The volume ledger keeps the certification mass balance honest. On a batch's first release, the batch's `ACTIVE` allocations are grouped by their lots' `supplier_id`; for each supplier, the drawn kilograms are summed into a `charged_kg` figure that is added to the `consumed_volume_kg` of that supplier's single `ACTIVE` grant of the matching `cert_type`, and the pairing of `certificate_id` and `charged_kg` is recorded in the batch's `cert_charges`, with charge entries appearing in the order in which each supplier first contributed an `ACTIVE` allocation to the batch. Recall is the exact inverse: each recorded charge is subtracted back from its grant's `consumed_volume_kg`, and the batch's `cert_charges` are emptied. Both legs carry three-decimal precision, so charge and restore cancel exactly, with no drift. At every moment, a grant's `consumed_volume_kg` equals the total charged kilograms across the batches currently `RELEASED` against it.

### 3.7. Packaging Lines, Run Scheduling, and Packed Shelf Life

`ProductionPlanner`s register each packaging line with a `name` and a `line_type` of `TEA_BAG` or `LOOSE_PACK`; lines start `ACTIVE`. Taking a line down moves it to `MAINTENANCE` — runs already `SCHEDULED` on it keep their bookings but cannot start while the line is down — and maintenance exit returns it to `ACTIVE`. Lines have no terminal state. Format discipline is strict throughout: the line's `line_type` must equal the packed batch's `pack_format`, or scheduling is rejected with `ERR_LINE_FORMAT_MISMATCH`, and neither scheduling nor starting is possible on a line in `MAINTENANCE` — both attempts fail with `ERR_LINE_NOT_ACTIVE`.

Scheduling a run books a window on a line. The request names the `line_id`, the `batch_id` of the batch to pack — which must be `RELEASED`, else `ERR_BATCH_NOT_RELEASABLE` — the `planned_start` and `planned_end` instants in ISO 8601 UTC, the `planned_units` count of at least one, and optionally a `contract_id` whose absence marks a house-label run. The window must open before it closes: a `planned_start` that is not strictly earlier than `planned_end` is rejected with `ERR_INVALID_WINDOW`. Windows are half-open — a run occupies its line from `planned_start` up to but not including `planned_end` — so when the new run's window intersects the window of another `SCHEDULED` or `IN_PROGRESS` run on the same line, the newcomer is rejected with `ERR_LINE_WINDOW_CONFLICT`, while back-to-back bookings that merely touch are allowed. Allergen changeover adds a spacing rule on top: when the new run would sit adjacent to another `SCHEDULED` or `IN_PROGRESS` run on the same line whose batch carries a different `allergen_tags` set, the gap between the two windows must be at least 45 minutes, and a tighter gap is rejected with `ERR_ALLERGEN_CHANGEOVER_BUFFER`. Contractual runs add further gates, detailed in §3.8. A successfully scheduled run starts life in `SCHEDULED` with its `provisional_shelf_life_days` already computed; its `actual_units`, `started_at`, `completed_at`, and `final_shelf_life_days` remain null until the corresponding events.

That estimate decays with moisture. The excess is the amount by which the batch's `measured_moisture_pct` exceeds the 5.0 percent target, or zero when it does not exceed it. The penalty takes that excess, multiplies it by ten, rounds the product up to the next whole number, and then multiplies by three days. The `provisional_shelf_life_days` is the pack format's base shelf life — 540 days for `TEA_BAG`, 365 days for `LOOSE_PACK` — minus the penalty.

Starting a run is a clock-gated act: the run must be `SCHEDULED`, the line must be `ACTIVE`, and the logical clock must read at or after `planned_start` and strictly before `planned_end` — a start outside that half-open window is rejected with `ERR_RUN_OUTSIDE_WINDOW`. A successful start stamps `started_at` from the logical clock and moves the run to `IN_PROGRESS`. Completion reports the `actual_units` produced — at least one, and at least the contract's per-run minimum when the run is contracted, else `ERR_PRIVATE_LABEL_MINIMUM_UNMET` — and requires the packed batch to still be `RELEASED`, else `ERR_BATCH_NOT_RELEASABLE`. Completion stamps `completed_at` from the logical clock and settles shelf life for good. For every lot with an `ACTIVE` allocation in the packed batch, the system counts the whole UTC calendar days between the lot's `harvest_date` and the completion date and subtracts that count from the 730-day harvest ceiling; the smallest such remainder across those lots becomes a floor, and the `final_shelf_life_days` is the smaller of the provisional estimate and that floor — strictly below the estimate whenever a constituent lot is old enough to bind the ceiling. The run then stands `COMPLETED`, and the completion also feeds the contract ledger of §3.8. Cancelling a run — directly by a `ProductionPlanner`, or through the cascades of §2.8 — is possible while it is `SCHEDULED`, frees its window, and moves it to `CANCELLED`. `COMPLETED` and `CANCELLED` are terminal; further actions meet `ERR_ALREADY_TERMINAL`.

### 3.8. Private-Label Contracts and Tiered Pricing

An `AccountManager` opens a private-label relationship by creating a contract that names the `customer_name`, the contracted `recipe_id`, the per-run floor `minimum_units_per_run` (at least one), the `contracted_total_units` volume (no smaller than the per-run floor), and a `base_unit_price_cents` of at least one cent. Contracts start in `DRAFT` with `fulfilled_units` at zero and `contract_unit_price_cents` null until activation computes it.

Activation prices the deal. The referenced recipe must be `ACTIVE`, else `ERR_RECIPE_NOT_ACTIVE`, and the `contract_unit_price_cents` is computed from the contract's base price, its total volume, and the recipe's certification target. Volume earns an average-rate discount applied to the whole price rather than marginally, read from `contracted_total_units` with inclusive tier boundaries: at least 10,000 units takes 5 percent off, at least 50,000 takes 10 percent, and at least 100,000 takes 15 percent — exactly 10,000 units already earns the 5 percent tier. Certification multiplies the price: 1.20 for an `ORGANIC` recipe, 1.10 for `FAIR_TRADE`, and 1.00 otherwise. The unit price is the `base_unit_price_cents` multiplied by the certification multiplier and by one minus the discount, rounded half-up to whole cents, and finally floored at the one-cent minimum — the greater of the rounded value and one cent wins. Activation moves the contract from `DRAFT` to `ACTIVE`. Cancellation is available from either `DRAFT` or `ACTIVE` and moves the contract to `CANCELLED`.

Runs settle the contract piece by piece. A run booked against a contract must reference an `ACTIVE` contract — a `DRAFT`, `CANCELLED`, or `FULFILLED` contract is rejected with `ERR_CONTRACT_NOT_ACTIVE` — and the contract's `recipe_id` must match the packed batch's recipe, else `ERR_CONTRACT_RECIPE_MISMATCH`. Both the `planned_units` given at scheduling and the `actual_units` reported at completion must reach the contract's `minimum_units_per_run`, else `ERR_PRIVATE_LABEL_MINIMUM_UNMET`. Each completion credits the contract's `fulfilled_units` with the run's `actual_units`, and the moment the accumulated total reaches or exceeds the `contracted_total_units`, the contract promotes itself from `ACTIVE` to `FULFILLED`. `FULFILLED` and `CANCELLED` are both terminal states, and actions attempted on either are rejected with `ERR_ALREADY_TERMINAL`.

## 4. Endpoint Definitions

Operations that create a new resource — a supplier, lot, flavoring, recipe, batch, line, run, contract, or certificate — or add a new record to a sub-collection — a grade assessment, residue test, allocation, or flavoring application — return `201 Created`. Operations that act on an existing resource without creating a new one, including all state-transition actions and recipe updates, return `200 OK`. Read endpoints answer `200 OK`. Read endpoints accept any of the nine declared roles, shown as "Any" below. List endpoints accept the optional filters noted in §3 — leaf lots by `supplier_id`, `leaf_type`, or `status`; recipes by `flavoring_id` or `status`; batches by `recipe_id` or `status`; runs by `line_id`, `batch_id`, `contract_id`, or `status`; certificates by `supplier_id`, `cert_type`, or `status`; contracts by `recipe_id` or `status` — in addition to the `limit` and `offset` pagination parameters of §2.3. Filters match by exact equality and, when several are given, combine conjunctively. The full request and response semantics of each endpoint are defined by the workflows of §3; this table is a locator, not a schema.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/tea-ops/suppliers` | Register a supplier | ProcurementLead |
| GET | `/tea-ops/suppliers/{id}` | Get a supplier | Any |
| POST | `/tea-ops/suppliers/{id}/suspend` | Suspend a supplier; cascades lot holds, batch holds, and run cancellations | ProcurementLead |
| POST | `/tea-ops/suppliers/{id}/reinstate` | Reinstate a suspended supplier (no automatic lot un-hold) | ProcurementLead |
| POST | `/tea-ops/leaf-lots` | Register a leaf lot | ProcurementLead |
| GET | `/tea-ops/leaf-lots/{id}` | Get a leaf lot | Any |
| GET | `/tea-ops/leaf-lots` | List leaf lots | Any |
| POST | `/tea-ops/leaf-lots/{id}/grade-assessments` | Submit a sensory grade assessment; computes the composite grade and transitions the lot | SensoryGrader |
| GET | `/tea-ops/leaf-lots/{id}/grade-assessments` | List grade assessments of a lot | Any |
| POST | `/tea-ops/leaf-lots/{id}/residue-tests` | Submit a pesticide residue test (initial or retest from hold); computes the verdict and transitions the lot | QALabAnalyst |
| GET | `/tea-ops/leaf-lots/{id}/residue-tests` | List residue tests of a lot | Any |
| POST | `/tea-ops/leaf-lots/{id}/release` | QA release of a tested lot (segregation of duties, supplier status, moisture gate) | QAManager |
| POST | `/tea-ops/leaf-lots/{id}/recall` | Recall a released lot; cascades batch holds and run cancellations | QAManager |
| GET | `/tea-ops/leaf-lots/{id}/allocations` | List allocations drawing from this lot | Any |
| POST | `/tea-ops/flavorings` | Register a flavoring agent | BlendMaster |
| GET | `/tea-ops/flavorings/{id}` | Get a flavoring | Any |
| POST | `/tea-ops/flavorings/{id}/retire` | Retire a flavoring; future applications are rejected | BlendMaster |
| GET | `/tea-ops/flavorings/{id}/flavoring-applications` | List applications of this flavoring | Any |
| POST | `/tea-ops/recipes` | Create a blend recipe (composition must sum to exactly 100.00) | BlendMaster |
| GET | `/tea-ops/recipes/{id}` | Get a recipe | Any |
| GET | `/tea-ops/recipes` | List recipes | Any |
| PUT | `/tea-ops/recipes/{id}` | Update a DRAFT recipe (optimistic concurrency on the recipe version) | BlendMaster |
| POST | `/tea-ops/recipes/{id}/activate` | Activate a recipe (re-validates composition and flavoring status) | BlendMaster |
| POST | `/tea-ops/recipes/{id}/retire` | Retire a recipe; cancels its DRAFT and RECIPE_LOCKED batches with allocation compensation | BlendMaster |
| POST | `/tea-ops/batches` | Create a blend batch for an ACTIVE recipe | BlendMaster |
| GET | `/tea-ops/batches/{id}` | Get a batch | Any |
| GET | `/tea-ops/batches` | List batches | Any |
| POST | `/tea-ops/batches/{id}/lock-recipe` | Pin the recipe version and compute required components and flavoring kilograms | BlendMaster |
| POST | `/tea-ops/batches/{id}/allocations` | Allocate kilograms from a RELEASED lot (optimistic concurrency on the batch version) | BlendMaster |
| GET | `/tea-ops/batches/{id}/allocations` | List allocations of a batch | Any |
| POST | `/tea-ops/batches/{id}/finalize-allocation` | Verify exact component fill and lot dominance; compute provisional cost | BlendMaster |
| POST | `/tea-ops/batches/{id}/blend` | Record post-blend moisture and compute moisture-adjusted yield | BlendMaster |
| POST | `/tea-ops/batches/{id}/apply-flavoring` | Apply the recipe's flavoring (allergen and organic rules, exact dose) | BlendMaster |
| GET | `/tea-ops/batches/{id}/flavoring-applications` | List flavoring applications of a batch | Any |
| POST | `/tea-ops/batches/{id}/submit-qc` | Submit the batch to quality control (unflavored, flavored, or rework branch) | BlendMaster |
| POST | `/tea-ops/batches/{id}/release` | QA release of the batch (moisture gate, certification chain and volume, segregation of duties) | QAManager |
| POST | `/tea-ops/batches/{id}/cancel` | Cancel a non-terminal batch; releases allocations back to lots | BlendMaster |
| POST | `/tea-ops/batches/{id}/recall` | Recall a released batch; restores certificate volume and cancels scheduled runs | QAManager |
| POST | `/tea-ops/packaging-lines` | Register a packaging line | ProductionPlanner |
| GET | `/tea-ops/packaging-lines/{id}` | Get a packaging line | Any |
| POST | `/tea-ops/packaging-lines/{id}/enter-maintenance` | Take a line down (blocks new runs and starts) | ProductionPlanner |
| POST | `/tea-ops/packaging-lines/{id}/exit-maintenance` | Return a line to service | ProductionPlanner |
| POST | `/tea-ops/runs` | Schedule a production run (format, batch, contract, overlap, and allergen changeover checks) | ProductionPlanner |
| GET | `/tea-ops/runs/{id}` | Get a run | Any |
| GET | `/tea-ops/runs` | List runs | Any |
| POST | `/tea-ops/runs/{id}/start` | Start a scheduled run (clock must be inside the window; line ACTIVE) | ProductionPlanner |
| POST | `/tea-ops/runs/{id}/complete` | Complete a run (batch still RELEASED; contract minimum; shelf-life finalized; fulfillment credited) | ProductionPlanner |
| POST | `/tea-ops/runs/{id}/cancel` | Cancel a scheduled run | ProductionPlanner |
| POST | `/tea-ops/contracts` | Create a private-label contract | AccountManager |
| GET | `/tea-ops/contracts/{id}` | Get a contract | Any |
| GET | `/tea-ops/contracts` | List contracts | Any |
| POST | `/tea-ops/contracts/{id}/activate` | Activate a contract (recipe must be ACTIVE); computes the tiered unit price | AccountManager |
| POST | `/tea-ops/contracts/{id}/cancel` | Cancel a DRAFT or ACTIVE contract | AccountManager |
| POST | `/tea-ops/certificates` | Grant a certificate (closed-interval overlap per supplier and type is rejected) | CertificationOfficer |
| GET | `/tea-ops/certificates/{id}` | Get a certificate | Any |
| GET | `/tea-ops/certificates` | List certificates | Any |
| POST | `/tea-ops/certificates/{id}/suspend` | Suspend a certificate; cascades batch holds and run cancellations | CertificationOfficer |
| POST | `/tea-ops/certificates/{id}/reinstate` | Reinstate a suspended certificate (validity must still cover the current date) | CertificationOfficer |
| POST | `/tea-ops/_clock/set_current_utc` | Set the logical clock; sweeps certificates into EXPIRED past their validity | PlatformAdmin |

## 5. Error Code Catalogue

The trigger condition for each error is defined by the narratives of §2 and §3; this catalogue is the authoritative identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_LOT_NOT_RELEASABLE` | 409 Conflict |
| `ERR_SUPPLIER_SUSPENDED` | 409 Conflict |
| `ERR_LOT_NOT_RELEASED` | 409 Conflict |
| `ERR_RECIPE_NOT_ACTIVE` | 409 Conflict |
| `ERR_BATCH_NOT_RELEASABLE` | 409 Conflict |
| `ERR_BATCH_NOT_FLAVORABLE` | 409 Conflict |
| `ERR_FLAVORING_REQUIRED` | 409 Conflict |
| `ERR_LINE_NOT_ACTIVE` | 409 Conflict |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_RUN_OUTSIDE_WINDOW` | 409 Conflict |
| `ERR_LINE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_ALLERGEN_CHANGEOVER_BUFFER` | 409 Conflict |
| `ERR_CERT_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_DUPLICATE_LOT_ALLOCATION` | 409 Conflict |
| `ERR_MOISTURE_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_SYNTHETIC_ON_ORGANIC` | 422 Unprocessable Entity |
| `ERR_CERT_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_CERT_VOLUME_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_RECIPE_COMPOSITION_INVALID` | 422 Unprocessable Entity |
| `ERR_ALLOCATION_TYPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ALLOCATION_GRADE_TOO_LOW` | 422 Unprocessable Entity |
| `ERR_LOT_WEIGHT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_FILL_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_SINGLE_LOT_DOMINANCE` | 422 Unprocessable Entity |
| `ERR_FLAVORING_MISMATCH` | 422 Unprocessable Entity |
| `ERR_FLAVORING_DOSE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_FLAVORING_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_CONTRACT_RECIPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_LINE_FORMAT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PRIVATE_LABEL_MINIMUM_UNMET` | 422 Unprocessable Entity |
