# Protein Bar & Functional Food Manufacturing API — Product Requirements Document

## 1. Introduction

A nutrition-bar co-manufacturer lives between two unforgiving disciplines: food-safety compliance and commercial commitment. On one side, every slab that enters a form-and-cut line inherits an allergen history from whatever ran before it, every protein claim printed on a wrapper must be substantiable twice — once on paper from nominal formulation assays and once against the actual supplier lots that went into the dough — and every shipped case must trace back to retain samples and a documented quality disposition. On the other side, brand customers sign co-manufacturing agreements carrying minimum run sizes, quarterly volume commitments, and tiered pricing, and they expect the plant to honor those terms even when a protein concentrate arrives with a certificate-of-analysis assay that drifts from nominal or a sweetener blend needs a last-minute top-up before the mixer starts.

This document specifies the Protein Bar & Functional Food Manufacturing API, the system of record for that plant. The API is mounted under the `/mfg` prefix and governs the complete operating loop: qualifying suppliers and registering ingredients, receiving and dispositioning ingredient lots, negotiating co-manufacturing agreements, developing formulas and verifying their nutrient claims, scheduling production runs on slab/form/cut lines under allergen changeover control, executing and completing runs, releasing finished lots under yield and retain gates, and tracking bar texture in stability chambers until labeled expiry. The design is compliance-first. Segregation of duties between laboratory measurement and quality decision is enforced structurally rather than procedurally, and a logical plant clock — never the wall clock — drives every time-dependent rule so that behavior is deterministic and auditable.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules that apply to every endpoint. Where a rule is specific to one workflow, it is stated here only in summary and in full in §3.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The declared roles are `PlantAdmin`, `FormulationScientist`, `QualityManager`, `ProductionPlanner`, `LabTechnician`, and `BrandCustomerRep`. A request whose `X-User-Role` header is missing or does not name one of these roles is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not on the addressed endpoint's authorized-role list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The roles divide the plant's duties deliberately. A `PlantAdmin` administers plant master data and infrastructure: suppliers, ingredients, ingredient-lot receipt, brand customers, agreements and their lifecycle, production lines, and the logical clock. A `FormulationScientist` owns formula development: revisions, their submission and routing to claim review, and claim-review submissions and resubmissions. A `QualityManager` holds quality authority: lot release and rejection, nutrition verification, revision approval and reject-back, pre-run verification, retain-sample registration, changeover validation and failure, lot-release decisions, and claim-review adjudication. A `ProductionPlanner` plans and executes: production-run creation, scheduling, start, completion, cancellation, and cleaning logistics. A `LabTechnician` records measurements — allergen swabs, shelf-life pulls, and QC dispositions — and opens and terminates shelf-life studies, but must never validate or decide what it recorded. A `BrandCustomerRep` is the external face of a brand customer, able to create formulas and claim reviews, resubmit claim reviews, and read everything belonging to its own customer.

For `PlantAdmin`, `FormulationScientist`, `QualityManager`, `ProductionPlanner`, and `LabTechnician`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `swab_recorded_by` on a changeover event, `validated_by` on a validated changeover, `qc_recorded_by` on a lot release, `decided_by` on a lot-release decision, or `reviewer_id` on a claim review — but it never compares the identifier to any entity's `id`.

When `X-User-Role` is `BrandCustomerRep`, `X-User-ID` is the `id` of the acting `BrandCustomer`; ownership checks on any resource that references a `BrandCustomer` compare the resource's foreign-key field to `X-User-ID`. A brand representative may therefore address only resources owned by its own customer record: listing and reading formulas, listing a formula's revisions, reading an individual revision, listing a revision's claim reviews, listing and reading agreements, reading an agreement's pricing quote, and listing and reading production runs are each scoped to the caller's own customer, as are formula creation and claim-review creation. On in-scope list endpoints the caller must pass `customer_id` equal to its own identifier; for the production-run listing, ownership resolves through the agreement each run belongs to. Any access by a `BrandCustomerRep` to a resource owned by a different brand customer — or an in-scope listing without that self-scoping — is rejected with `ERR_FORBIDDEN_CUSTOMER_SCOPE` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0.

Unless stated otherwise, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order.

List responses carry four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Versioning, and the Plant Logical Clock

Every resource in this system — suppliers, ingredients, ingredient lots, brand customers, agreements, formulas, revisions, production lines, line slots, production runs, changeover events, shelf-life studies, shelf-life pulls, lot releases, retain samples, and claim reviews — carries the same four system-managed properties:

- `id` (string): a server-minted UUID with no type prefix, assigned at creation.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at its initial value at creation and increments by exactly one on every mutation.

As a rule, every state transition, field update, and system-driven reconciliation described in this document is a mutation: it increments the owning resource's `version` by one and refreshes its `updated_at`, and where one operation touches several resources — for example, a cascade that releases reservations across many runs — each touched resource's `version` increments independently. The only exceptions are the bookkeeping-free system transitions explicitly noted as such in §3.7.

All time-dependent behavior in the plant is governed by a single **logical clock**, not by the server's wall clock. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and it must never silently fall back to wall-clock time. A `PlantAdmin` advances the clock through an admin-only clock-setting capability that accepts a `to_iso8601` instant and answers with the resulting `current_utc`. Setting the clock is itself an evaluation trigger: studies whose labeled expiry has been passed are auto-completed when their texture projection passes, and shelf-life pulls whose grace window has elapsed are marked missed, as detailed in §3.9. Scheduling rules that reference "now" — the prohibition on scheduling into the past, the pull-recording window, the wet-clean staleness measurement — all read this logical clock.

### 2.5. Optimistic Concurrency Control

Two write operations guard their parent aggregate with optimistic concurrency control; no other endpoint accepts a version field.

Creating a production run requires the request to carry `expected_agreement_version`, the client-observed `version` of the target agreement. Because every successful run creation debits the agreement's committed-volume ledger and increments the agreement's `version` by one, a client holding an older observed version is acting on a stale agreement state; if `expected_agreement_version` does not match the agreement's current `version`, the creation is rejected with `ERR_STALE_VERSION` (HTTP 412).

Scheduling a production run requires the request to carry `expected_line_version`, the client-observed `version` of the target production line. Because every successful schedule creates a line slot plus a changeover event and increments the line's `version` by one, a client holding an older observed version computed its overlap and buffer checks against a stale occupancy picture; if `expected_line_version` does not match the line's current `version`, the schedule is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.6. Validation Cascade and Error Ordering

Every request is validated against a fixed cascade, and an earlier failure masks every later check. The cascade runs in this order:

1. **Authentication** — the `X-User-Role` header must be present and name a declared role, else `ERR_UNAUTHENTICATED` (401).
2. **Role authorization** — the acting role must appear in the endpoint's authorized-role list, else `ERR_UNAUTHORIZED_ROLE` (403).
3. **Brand-customer scope** — a `BrandCustomerRep` must satisfy the ownership rules of §2.1, else `ERR_FORBIDDEN_CUSTOMER_SCOPE` (403).
4. **Path existence** — every identifier in the URL path must resolve, validated left to right (see §2.10), each missing resource producing its own 404.
5. **Body foreign keys** — every identifier carried in the request body (`ingredient_id`, `supplier_id`, `customer_id`, `revision_id`, `agreement_id`, `line_id`, `run_id`, and each `ingredient_id` inside `ingredient_lines`) must reference an existing resource, producing the corresponding 404.
6. **Request shape** — required fields present, types correct, numeric ranges honored, and required arrays non-empty, else `ERR_INVALID_REQUEST` (400).
7. **Enum membership** — enum-typed fields must carry a declared member, else `ERR_INVALID_ENUM_VALUE` (400).
8. **Terminal-state lock** — the addressed resource must not sit in a terminal state: a `TERMINATED` agreement, a `SUPERSEDED` revision, a `REJECTED` or `DEPLETED` lot, a `CANCELLED` run or changeover, a lot release whose decision is `RELEASED` or `SCRAPPED`, or a `COMPLETED`, `FAILED`, or `TERMINATED` study all reject further action with `ERR_TERMINAL_STATE_LOCKED` (409).
9. **State-machine legality** — the resource's own state machine must permit the requested transition from its current state, else `ERR_INVALID_STATE` (409).

Only after all nine generic stages pass are the endpoint-specific business rules evaluated, in the explicit per-endpoint orders stated throughout §3.

### 2.7. Allergen Governance and Segregation of Duties

The plant recognizes seven allergens as exact enumeration values: `MILK`, `SOY`, `PEANUT`, `TREE_NUT`, `WHEAT`, `EGG`, and `SESAME`. Allergens are declared at three levels: a supplier records the allergens handled at its site in `allergens_handled`, an ingredient records the allergens it carries in `allergen_tags`, and a formula revision inherits a computed `allergen_profile` (§3.4). Two allergens are designated **high-risk**: `PEANUT` and `TREE_NUT`; their presence in carryover residue escalates changeover control to its most stringent level (§3.7).

Two segregation-of-duties pairs are enforced by identity, not by policy memo. The `QualityManager` who validates a swab-controlled changeover must be a different `X-User-ID` than the `LabTechnician` who recorded the swab, and the `QualityManager` who decides a finished lot must be a different `X-User-ID` than the `LabTechnician` who recorded its QC disposition; either collision is rejected with `ERR_SOD_VIOLATION` (HTTP 422). A validated allergen swab must read at most 20 parts per million; a swab reading above that limit cannot be validated and is rejected with `ERR_SWAB_PPM_EXCEEDS_LIMIT` (HTTP 422).

A gluten-free segregation rule guards the line itself: a revision claiming `GLUTEN_FREE` may not be planned on a line whose `current_allergen_profile` contains `WHEAT` — the attempt is rejected at run creation with `ERR_ALLERGEN_SEGREGATION_VIOLATION` (HTTP 422).

### 2.8. Inventory Mass Conservation

Every ingredient lot is a small ledger governed by a conservation invariant: its `available_qty_kg` always equals its `received_qty_kg` minus its `reserved_qty_kg` minus its `consumed_qty_kg`. Reservations are created when a production run is planned, drawing first-in-first-out from `RELEASED` lots of the required ingredient ordered by `received_at` ascending with ties broken by `created_at` ascending; each reservation entry on the run records the `lot_id`, the `ingredient_id`, and the reserved `qty_kg`. Consumption happens when a run actually starts production, moving quantity from `reserved_qty_kg` into `consumed_qty_kg` without changing `available_qty_kg`. A lot whose consumption leaves `available_qty_kg` at exactly zero, with `reserved_qty_kg` also at zero and `consumed_qty_kg` equal to `received_qty_kg`, automatically transitions to `DEPLETED`.

### 2.9. Numerical Precision and Rounding

Unless a calculation states otherwise, computed numeric values are rounded half-up to exactly two decimal places. Two calculations pin their rounding order and are called out where they are defined: protein-per-serving substantiation rounds each ingredient line's contribution to two decimal places before summing, then rounds again after each subsequent division (§3.4), and the cut plan floors each slab's bar count before multiplying by the slab count (§3.8). Agreement pricing is exact integer arithmetic in cents, with the per-case figure rounded half-up to a whole cent (§3.3). Case counts, slab counts, and minute figures are integers throughout; the cut plan and bar-per-batch derivations round down to whole units as specified. Sweetener requirements are rounded up to the nearest hundredth of a kilogram (§3.6, §3.8).

### 2.10. Nested Resource Resolution and Cross-Entity Consistency

Endpoints whose paths contain several identifiers resolve them strictly left to right. The first identifier that does not correspond to an existing resource fails the request with that resource type's own 404 before any later identifier is examined: a missing brand customer yields `ERR_CUSTOMER_NOT_FOUND`, a missing formula `ERR_FORMULA_NOT_FOUND`, a missing revision `ERR_REVISION_NOT_FOUND`, a missing ingredient `ERR_INGREDIENT_NOT_FOUND`, a missing lot `ERR_LOT_NOT_FOUND`, a missing line `ERR_LINE_NOT_FOUND`, a missing run `ERR_RUN_NOT_FOUND`, a missing agreement `ERR_AGREEMENT_NOT_FOUND`, a missing slot `ERR_SLOT_NOT_FOUND`, a missing changeover `ERR_CHANGEOVER_NOT_FOUND`, a missing study `ERR_STUDY_NOT_FOUND`, a missing lot release `ERR_RELEASE_NOT_FOUND`, a missing claim review `ERR_CLAIM_REVIEW_NOT_FOUND`, and a missing supplier `ERR_SUPPLIER_NOT_FOUND`. A request for a revision beneath a nonexistent formula therefore fails with `ERR_FORMULA_NOT_FOUND` before the revision identifier is ever considered.

Consistency across aggregates is maintained by the server itself through cascades and automatic transitions rather than by client choreography. Two depth-limited cascades anchor this principle: rejecting a released lot unwinds reservations, readiness, and schedules across every affected run (§3.2), and approving a formula revision supersedes its predecessor and cancels the predecessor's open runs (§3.4). Where a reconciliation touches multiple resources, each touched resource's `updated_at` refreshes and its `version` increments, per §2.4.

## 3. Business Logic & Workflows

### 3.1. Supplier Qualification and the Ingredient Registry

Before any dough can be mixed, the plant must know who it buys from and what it buys. A `PlantAdmin` registers each supplier with a legal `name` and the allergens handled at the supplier's site in `allergens_handled`, which defaults to an empty list when omitted. Every supplier begins life with `qualification_status` `PROVISIONAL`. Qualification is a deliberate act: a `PlantAdmin` updates the supplier record to move `qualification_status` from `PROVISIONAL` to `APPROVED`, from `APPROVED` to `SUSPENDED`, or from `SUSPENDED` back to `APPROVED`, each change incrementing the supplier's `version`. Only `APPROVED` suppliers may deliver ingredient lots (§3.2). The supplier listing can be filtered by `qualification_status`.

Ingredients are registered by a `PlantAdmin` with a `name`, a functional `category` drawn from `PROTEIN`, `SWEETENER`, `BINDER`, `FAT`, `FLAVOR`, and `ADDITIVE`, and the allergen values the ingredient carries in `allergen_tags` (defaulting to empty). The category drives which nominal assay is mandatory: an ingredient whose `category` is `PROTEIN` must declare `nominal_protein_pct`, a protein fraction greater than zero and at most one; an ingredient whose `category` is `SWEETENER` must declare `nominal_sweetness_factor`, a relative sweetness factor greater than zero. An ingredient's `status` starts `ACTIVE`; once marked `DISCONTINUED`, it can no longer appear in a newly submitted formula revision (§3.4). The ingredient listing can be filtered by `category` and by `status`.

### 3.2. Ingredient Lot Intake and Disposition

Receiving a lot is the moment supplier variability enters the plant's books. A `PlantAdmin` receives an ingredient lot by naming the `ingredient_id` and `supplier_id`, the supplier's `lot_code`, the `received_qty_kg` (greater than zero, expressed to two decimal places), and the receipt instant `received_at`. The certificate-of-analysis assays mirror the ingredient's nominal fields: when the ingredient is a `PROTEIN`, the receipt must carry `coa_protein_pct` (greater than zero and at most one); when it is a `SWEETENER`, the receipt must carry `coa_sweetness_factor` (greater than zero). Two gates guard receipt, evaluated in order: first the referenced supplier's `qualification_status` must be `APPROVED`, otherwise the receipt is rejected with `ERR_SUPPLIER_NOT_QUALIFIED` (HTTP 422); then the `lot_code` must be unique within its ingredient across all lots that are not `REJECTED`, otherwise the receipt is rejected with `ERR_DUPLICATE_LOT_CODE` (HTTP 409). Every lot arrives in `QUARANTINE`, unavailable for reservation. The lot listing can be filtered by `ingredient_id`, by `supplier_id`, and by `status`.

Disposition belongs to the `QualityManager`. Releasing a quarantined lot moves its `status` from `QUARANTINE` to `RELEASED`, making it eligible for the reservation ledger of §2.8. Rejection from `QUARANTINE` simply moves the lot to `REJECTED`, a terminal state. Rejecting a lot that is already `RELEASED`, however, triggers the three-link **CASCADE-REJECT**. Link one: every open reservation on the lot is released — for each production run in `PLANNED` or `SCHEDULED` holding an allocation on this lot, the allocation is removed from the run's `reserved_lot_allocations` and the lot's `reserved_qty_kg` is decremented by the released quantity. Link two: each such run recomputes its `ingredient_readiness`, and any run whose ingredient lines are no longer fully reserved drops to `BLOCKED`. Link three: a run whose readiness flipped from `READY` to `BLOCKED` while sitting in `SCHEDULED` automatically falls back to `PLANNED` with `cancel_reason` `INGREDIENT_SHORTAGE`; its line slot moves from `CONFIRMED` to `RELEASED`, and its changeover event moves to `CANCELLED`. The lot's `version` and every touched run's `version` each increment by one. Runs that have already advanced past `SCHEDULED` are outside the cascade's reach.

The lot's final transition is automatic: once consumption brings `available_qty_kg` to exactly zero while nothing remains reserved, the lot moves from `RELEASED` to `DEPLETED`, a terminal state, per the conservation invariant of §2.8.

### 3.3. Brand Customers and Co-Manufacturing Agreements

A `PlantAdmin` registers each brand customer with a `name` and a primary `contact_email`; the customer's `status` begins `ACTIVE`. A customer whose `status` is `SUSPENDED` cannot be the subject of a new formula or a new agreement, and no production run may be created under its agreements — each attempt is rejected with `ERR_CUSTOMER_SUSPENDED` (HTTP 422). The customer listing can be filtered by `status`.

The commercial spine of the plant is the **ManufacturingAgreement**, created by a `PlantAdmin` in `NEGOTIATION` status against a `customer_id`. The agreement fixes the commercial terms up front: a `pricing_mode` of `MARGINAL` or `AVERAGE`; a `moq_cases_per_run` floor on every run's planned output, greater than zero and inclusive at the boundary so a run planning exactly the minimum passes; a `committed_cases_per_quarter` volume commitment, greater than zero; a `tier_breaks` table of pricing tiers, each pairing an `upto_cases` ceiling with an integer `rate_cents_per_case`, sorted ascending by `upto_cases` and always ending in a final tier whose `upto_cases` is exactly 999999999; and a `quarter_start` anchoring the commitment calendar. The **quarter window** is the 91-day interval opening at `quarter_start` (inclusive) and closing 91 days later (exclusive).

Activation, suspension, and termination are `PlantAdmin` actions on the agreement. Activation moves `status` from `NEGOTIATION` to `ACTIVE` and requires the owning customer to be `ACTIVE`. Suspension moves an `ACTIVE` agreement to `SUSPENDED`; resumption moves a `SUSPENDED` agreement back to `ACTIVE`, again requiring the owning customer to be `ACTIVE`. Termination from either `ACTIVE` or `SUSPENDED` moves the agreement to `TERMINATED`, which is terminal. Each transition increments the agreement's `version`. The agreement listing can be filtered by `customer_id` and by `status`.

Two computed figures track the agreement's quarterly health, recomputed whenever a lot-release decision lands (§3.8). The `produced_cases_current_quarter` is the sum of `produced_cases` over the agreement's runs whose `release_status` is `RELEASED` and whose `completed_utc` falls inside the quarter window — a completion exactly at `quarter_start` counts, one exactly at the window's end does not. The `shortfall_cases` is the committed volume minus that produced volume, floored at zero, so it can never report a negative shortfall.

The agreement also prices hypothetical volumes through its quote capability, which accepts a requested `cases` count and answers with the echoed `cases`, a `total_cents`, and a `per_case_cents`. Under `MARGINAL` pricing, the quote walks the tier table in ascending order and charges each tier's `rate_cents_per_case` only to the cases falling inside that tier's bracket — for each tier, the cases charged are the smaller of the requested count and the tier's `upto_cases`, minus the cases already charged to lower tiers, never less than zero — and the total is the sum of those per-tier charges. Under `AVERAGE` pricing, the quote finds the first tier whose `upto_cases` reaches the requested count and applies that single tier's rate to every case; when tier rates descend, this yields a strictly lower total than `MARGINAL` for any request above the first tier. In both modes `total_cents` is an exact integer of cents, and `per_case_cents` is the total divided by the case count, rounded half-up to a whole cent.

### 3.4. Formulas and the Revision Pipeline

A formula is a brand customer's product definition, created by a `FormulationScientist` or a `BrandCustomerRep` with the owning `customer_id`, a display `name`, the finished `bar_weight_g` (greater than zero), and an optional `serving_count_per_bar` (at least one, defaulting to one, so a bar is exactly one serving by default). Creating a formula requires the referenced customer to be `ACTIVE`, failing with `ERR_CUSTOMER_SUSPENDED` otherwise. A formula's `status` begins `ACTIVE`; once `ARCHIVED`, it cannot receive new revisions, new shelf-life studies, or — transitively, through its revisions — new production runs, and attempts to create a revision or study against it are rejected with `ERR_FORMULA_ARCHIVED` (HTTP 422). The formula's `approved_revision_id` is a computed pointer, not a stored foreign key: it is the `id` of the formula's unique `APPROVED` revision, or null while no revision has been approved. The formula listing can be filtered by `customer_id` and by `status`.

Formula content lives in **FormulaRevisions**. A `FormulationScientist` drafts a revision beneath a formula with its `ingredient_lines` — at least one line required, each line naming an `ingredient_id`, a `qty_kg_per_batch` greater than zero, and an `is_protein_contributor` flag — plus the total `batch_size_kg` (greater than zero), a `target_protein_g_per_serving` (zero or more), and optionally `claim_tags`, the label claims the revision will carry: `HIGH_PROTEIN`, `GOOD_SOURCE_PROTEIN`, `LOW_SUGAR`, and `GLUTEN_FREE`, defaulting to none. At creation the revision records its parent in `formula_id`, receives a `revision_no`, a 1-based sequence number within its formula assigned in creation order, and a computed `allergen_profile`: the union of the `allergen_tags` of every ingredient referenced by its lines, sorted alphabetically. A new revision starts in `DRAFT`, and both of its computed protein figures — `label_protein_g_per_serving` and `composite_protein_g_per_serving` — are null until the workflows below populate them. The revision listing beneath a formula can be filtered by `status`.

Submission by the `FormulationScientist` moves a revision from `DRAFT` to `SUBMITTED`. Two referential checks are evaluated in order: first, every ingredient referenced by the revision's lines must still be `ACTIVE`, else the submission is rejected with `ERR_INGREDIENT_DISCONTINUED` (HTTP 422); second, the parent formula must still be `ACTIVE`, else the submission is rejected with `ERR_FORMULA_ARCHIVED`.

Nutrition verification is a `QualityManager` act that moves the revision from `SUBMITTED` to `NUTRITION_VERIFIED` and computes the **LABEL variant** of the protein substantiation. The calculation proceeds as follows. The batch yield in bars is the revision's `batch_size_kg` converted to grams and divided by the formula's `bar_weight_g`, rounded down to a whole number of bars. For every ingredient line flagged `is_protein_contributor`, the line's protein contribution in grams is the line's `qty_kg_per_batch` converted to grams and multiplied by the ingredient's `nominal_protein_pct`, rounded half-up to two decimal places. Those rounded contributions are summed, divided by the bars per batch, and rounded half-up to two decimal places to give grams of protein per bar; that figure is divided by the formula's `serving_count_per_bar` and rounded half-up to two decimal places to give grams of protein per serving. The rounding order is pinned: each line contribution is rounded before the sum, and each division is rounded after it is performed — summing unrounded contributions and rounding once at the end is a different, incorrect procedure. The result is written to the revision's `label_protein_g_per_serving`. Verification then gates on the revision's claims: the LABEL result must satisfy every `NUTRIENT_CONTENT` claim in `claim_tags` — at least 10.0 grams per serving for `HIGH_PROTEIN` and at least 5.0 grams per serving for `GOOD_SOURCE_PROTEIN` — or the verification is rejected with `ERR_LABEL_CLAIM_UNSUBSTANTIATED` (HTTP 422). A successful verification also recomputes `substantiation_ok` on every non-terminal claim review of the revision (§3.5) and increments the revision's `version`.

Once nutrition is verified, the `FormulationScientist` routes the revision to claim review, moving it from `NUTRITION_VERIFIED` to `CLAIM_REVIEW`. From there the `QualityManager` holds two outcomes. Approval moves the revision from `CLAIM_REVIEW` to `APPROVED` and is permitted only when every claim tag in `claim_tags` has exactly one claim review in `APPROVED` status; a missing or unapproved review for any claimed tag rejects the approval with `ERR_CLAIM_REVIEW_INCOMPLETE` (HTTP 422). Approval fires the two-link **CASCADE-SUPERSEDE**: the previously `APPROVED` revision of the same formula, if one exists, moves to `SUPERSEDED` (a terminal, self-referential transition within the formula's own revision set); and every production run still in `PLANNED` or `SCHEDULED` that references the superseded revision is automatically `CANCELLED` with `cancel_reason` `FORMULA_SUPERSEDED`, its line slot moving from `CONFIRMED` to `RELEASED`, its changeover event moving to `CANCELLED`, and its lot reservations released with each affected lot's `reserved_qty_kg` decremented. The approving revision's `version` and every touched run's `version` increment by one, and the formula's `approved_revision_id` is recomputed to point at the newly approved revision. The alternative outcome, reject-back, moves the revision from `CLAIM_REVIEW` back to `DRAFT` for reformulation; a revision may loop through draft, submission, verification, and review as many times as needed.

### 3.5. Claim Review and Label Substantiation

Every tag in a revision's `claim_tags` must survive an independent adjudication before the revision can be approved. A claim review is opened against a `revision_id` by a `FormulationScientist` or a `BrandCustomerRep`, naming the `claim_tag` under review and its `claim_type` — `NUTRIENT_CONTENT` or `STRUCTURE_FUNCTION` — and, for structure/function claims, whether the required FTC disclaimer appears on the label via `structure_function_disclaimer` (defaulting to false). The review starts in `SUBMITTED`, and its `substantiation_ok` is computed at creation from the revision's current computed fields.

The substantiation gate evaluates each claim against a precise predicate. `HIGH_PROTEIN` is substantiated when the revision's `label_protein_g_per_serving` is at least 10.0 grams. `GOOD_SOURCE_PROTEIN` is substantiated at 5.0 grams per serving or more. `LOW_SUGAR` derives a sugar load per bar — the sweetener lines' `qty_kg_per_batch` figures are summed, converted to grams, divided by the batch's bar yield as computed in §3.4, and rounded half-up to two decimal places — and is substantiated when that figure is at most 4.0 grams per bar, the boundary included. `GLUTEN_FREE` is substantiated when `WHEAT` does not appear in the revision's `allergen_profile`. A `STRUCTURE_FUNCTION` review carries one further requirement, enforced at approval time: `structure_function_disclaimer` must be true.

Adjudication belongs to the `QualityManager`. Starting a review moves it from `SUBMITTED` to `IN_REVIEW`. Approval from `IN_REVIEW` enforces its guards in order: the parent revision must currently stand in `NUTRITION_VERIFIED` or `CLAIM_REVIEW` so that label substantiation exists (otherwise `ERR_INVALID_STATE`, HTTP 409); `substantiation_ok` must be true (otherwise `ERR_LABEL_CLAIM_UNSUBSTANTIATED`, HTTP 422); and a `STRUCTURE_FUNCTION` review must carry `structure_function_disclaimer` true (otherwise `ERR_DISCLAIMER_REQUIRED`, HTTP 422). Approval stamps the review's `reviewer_id` with the approver's `X-User-ID` and is terminal. Requesting revision moves the review from `IN_REVIEW` to `REVISION_REQUESTED`, also stamping `reviewer_id`, and a subsequent resubmission by a `FormulationScientist` or `BrandCustomerRep` returns it to `SUBMITTED` with `substantiation_ok` recomputed — the review may cycle through submission, review, and revision-request repeatedly. Because `substantiation_ok` derives from the revision's computed fields, a successful nutrition verification (§3.4) also refreshes it on every review of that revision that has not yet reached `APPROVED`.

### 3.6. Production Run Planning and Line Scheduling

Production capacity is modeled as **ProductionLines**, each registered by a `PlantAdmin` with a `name`, a `line_type` (currently always `SLAB_FORM_CUT`, its default), a rated `capacity_kg_per_hour` greater than zero, and the `slab_weight_kg` fed to the form-and-cut section (greater than zero — this weight drives the cut plan of §3.8). Two system-maintained fields track the line's allergen memory: `current_allergen_profile`, the allergen profile of the most recent run to reach production on this line (empty until the line has run), and `last_wet_clean_utc`, the logical-clock timestamp of the most recent validated wet clean or swab-validated changeover (null until one occurs). The line listing supports the standard pagination.

A `ProductionPlanner` creates a production run by naming the `revision_id`, the `agreement_id`, the `line_id`, the `planned_cases` output (a whole number of cases, greater than zero, at twelve bars per case), and `expected_agreement_version` per §2.5. Run creation evaluates its gates in a fixed order: first the gluten-free segregation rule of §2.7 (`ERR_ALLERGEN_SEGREGATION_VIOLATION`); then the referenced revision must stand in `APPROVED` (`ERR_REVISION_NOT_APPROVED`, HTTP 422); then the referenced agreement must be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`, HTTP 422); then the agreement's customer must be `ACTIVE` (`ERR_CUSTOMER_SUSPENDED`); then `planned_cases` must meet the agreement's `moq_cases_per_run`, the boundary inclusive (`ERR_MOQ_SHORTFALL`, HTTP 422); and finally the stale-version check of §2.5 (`ERR_STALE_VERSION`, HTTP 412).

A successfully created run lands in `PLANNED` on its production axis and `NOT_READY` on its quality-disposition axis — the run carries two parallel state dimensions, `status` and `release_status`, and the release axis never mutates the production axis. Creation also performs the run's ingredient bookkeeping. Reservations are drawn FIFO from `RELEASED` lots per §2.8 and stored on the run as `reserved_lot_allocations`; the run's `ingredient_readiness` is computed as `READY` when every ingredient line of the revision is fully reserved and `BLOCKED` otherwise; and the provisional sweetener requirement is computed and stored as `provisional_sweetener_required_kg`. For each line whose ingredient is a `SWEETENER`, the provisional requirement is the line's `qty_kg_per_batch` multiplied by the ingredient's `nominal_sweetness_factor` and divided by the same nominal factor — the line quantity itself — rounded up to the nearest hundredth of a kilogram, and the stored figure is the sum over all sweetener lines. The run receives a system-minted `batch_code`: the literal prefix `BATCH-` followed by a zero-padded 1-based count of the runs created before it, in creation order. Because the new run debits the agreement's committed-volume ledger, the agreement's `version` increments by one. The run listing can be filtered by `revision_id`, `agreement_id`, `line_id`, and `status`.

Scheduling places the run on its line's calendar. A `ProductionPlanner` schedules a `PLANNED` run by supplying a `start_utc` and an `end_utc` — the end must be later than the start — together with `expected_line_version` per §2.5. The schedule's checks run in order: the slot must not begin in the past relative to the logical clock (`ERR_SCHEDULE_IN_PAST`, HTTP 422); the half-open interval from `start_utc` (inclusive) to `end_utc` (exclusive) must not intersect any `CONFIRMED` slot on the same line, with touching endpoints permitted (`ERR_SLOT_OVERLAP`, HTTP 409); the gap to each adjacent `CONFIRMED` slot must be at least the changeover buffer this run requires (`ERR_SLOT_CHANGEOVER_BUFFER_VIOLATION`, HTTP 409); and the line's `version` must match `expected_line_version` (`ERR_STALE_VERSION`).

A successful schedule performs three creations at once. A line slot is created in `CONFIRMED` status, exactly one slot per run, carrying the run's `line_id`, the run's `run_id`, the supplied `start_utc` and `end_utc`, and a computed `buffer_minutes` taken from the required changeover level: 0 minutes for `NONE`, 30 for `DRY_CLEAN`, 60 for `WET_CLEAN`, and 90 for `SWAB_VALIDATE`. A changeover event is created linking the previous run on this line — the run with the latest `end_utc`, ties broken by earliest `created_at`, or a null `from_run_id` when the line has never hosted a run — to this run as `to_run_id`, with `required_level` computed per §3.7; an event whose level is `NONE` is created directly in `VALIDATED`, while every other level begins `PENDING`. And both the line's `version` and the run's `version` increment by one. The slots of a line can be listed and filtered by `status`, as can the changeover events on a line; the run's own slot and the changeover events where the run appears as either leg can be listed from the run's perspective.

Planners can also read a line's computed per-day occupancy for any UTC calendar day by supplying a `date`. The answer echoes the `date` and reports `occupied_minutes` — the sum, over the line's `CONFIRMED` slots, of each slot's overlap with the day window running from midnight UTC of that date (inclusive) to midnight UTC of the next (exclusive) — plus `buffered_minutes`, the sum of `buffer_minutes` over the `CONFIRMED` slots whose `start_utc` falls inside that day, and `free_minutes`, the day's 1,440 minutes minus occupied minus buffered. Free minutes are never negative, and scheduling a slot followed by its compensating cancellation or release restores the day's free minutes exactly.

### 3.7. Allergen Changeover Control

The changeover level matrix converts allergen arithmetic into cleaning severity. The computation compares the previous run's allergen profile on this line (the **from-profile**, empty when the line has never run) with the incoming run's revision `allergen_profile` (the **to-profile**). The **carryover set** is the residue: allergens present in the from-profile but absent from the to-profile. The level is decided by the first rule that matches, in this order: when the from-profile is empty, the level is `NONE`; when the carryover set is empty — everything the line last ran is also declared on the incoming product — the level is `DRY_CLEAN`; when the carryover set contains a high-risk allergen (`PEANUT` or `TREE_NUT`) or spans two or more distinct allergens, the level is `SWAB_VALIDATE`; otherwise, when more than 1,440 minutes — a full 24-hour day — have elapsed on the logical clock since the line's `last_wet_clean_utc`, or no wet clean has ever been validated, the level is `SWAB_VALIDATE` as well; and in every remaining case the level is `WET_CLEAN`.

Events requiring cleaning follow a measured-then-decided workflow with segregation of duties. A `ProductionPlanner` logs the cleaning, moving the event from `PENDING` to `CLEANING_LOGGED`; this step applies to levels `DRY_CLEAN`, `WET_CLEAN`, and `SWAB_VALIDATE`. An event that has `FAILED` may be re-cleaned: logging the cleaning again returns it from `FAILED` to `CLEANING_LOGGED` and clears its previous `swab_allergen_ppm` and `swab_recorded_by`. A `LabTechnician` then records the allergen swab, moving the event from `CLEANING_LOGGED` to `SWAB_RECORDED` — but only when the event's `required_level` is `SWAB_VALIDATE`; recording a swab on any other level is rejected with `ERR_SWAB_NOT_REQUIRED` (HTTP 422). Recording stores the measured `swab_allergen_ppm` and stamps `swab_recorded_by` with the technician's `X-User-ID`.

Validation is the `QualityManager`'s signature. For events at level `DRY_CLEAN` or `WET_CLEAN`, validation moves the event directly from `CLEANING_LOGGED` to `VALIDATED`; a swab-controlled event must instead pass through `SWAB_RECORDED`, where validation enforces two guards in order — the recorded `swab_allergen_ppm` must be at most 20 parts per million (`ERR_SWAB_PPM_EXCEEDS_LIMIT`, HTTP 422), and the validator's `X-User-ID` must differ from `swab_recorded_by` (`ERR_SOD_VIOLATION`, HTTP 422). Every validation stamps `validated_by` with the validator's `X-User-ID`, and validating either a `WET_CLEAN` or a `SWAB_VALIDATE` event refreshes the line's `last_wet_clean_utc` to the current logical clock, incrementing the line's `version`. Alternatively, a `QualityManager` may fail a swab-controlled event from `SWAB_RECORDED`, moving it to `FAILED` and starting the re-clean loop above. `VALIDATED` is terminal. When the run an event feeds is cancelled or de-scheduled, the system moves the event to `CANCELLED` from `PENDING`, `CLEANING_LOGGED`, or `FAILED`; these system cancellations are bookkeeping-only and do not increment the event's `version`.

### 3.8. Run Execution, Completion, and Lot Disposition

Before a scheduled run may start, a `QualityManager` performs pre-run verification, moving the run from `SCHEDULED` to `PRE_RUN_VERIFIED`. Verification evaluates three gates in order. First, the **COMPOSITE variant** of the protein substantiation must satisfy every `NUTRIENT_CONTENT` claim in the revision's `claim_tags`, otherwise the verification is rejected with `ERR_COMPOSITE_CLAIM_UNSUBSTANTIATED` (HTTP 422). The composite calculation follows the same shape as the LABEL variant of §3.4 — same pinned rounding order, same 10.0 and 5.0 gram-per-serving thresholds — except that each protein-contributing line's fraction comes from the reserved supplier lots rather than the nominal assay: the sum, across the run's `reserved_lot_allocations` entries for that ingredient, of each entry's `qty_kg` multiplied by its lot's `coa_protein_pct`, divided by the total reserved kilograms for that ingredient. A protein-contributing line with zero reserved kilograms leaves the composite variant undefined, and verification fails with `ERR_INGREDIENT_SHORTAGE` (HTTP 422). Second, the changeover event feeding this run must stand in `VALIDATED` (`ERR_CHANGEOVER_NOT_VALIDATED`, HTTP 422). Third, the run's `ingredient_readiness` must be `READY`, and the sweetener top-up below must succeed (both failures surface as `ERR_INGREDIENT_SHORTAGE`).

Successful verification writes two computed figures. The composite protein result is stored on the revision as `composite_protein_g_per_serving`, which is null until a run of that revision passes this gate. And the **FINAL variant** of the sweetener adjustment is stored on the run as `final_sweetener_required_kg`: for each sweetener line, the line's `qty_kg_per_batch` multiplied by the ingredient's `nominal_sweetness_factor` and divided by the reserved-lot weighted sweetness factor — the sum of each allocation entry's `qty_kg` times its lot's `coa_sweetness_factor`, divided by the total reserved kilograms — rounded up to the nearest hundredth of a kilogram, then summed over the sweetener lines. The final figure differs from the provisional one whenever a reserved lot's certificate factor differs from nominal. When the final requirement exceeds what is already reserved, the run tops up its sweetener reservations by the difference, drawing from the same ingredient's remaining available `RELEASED` lots oldest-receipt first with ties broken by creation order; if the available quantity cannot cover the delta, the transition fails with `ERR_INGREDIENT_SHORTAGE`. A successful verification increments the run's `version`.

Starting production is the `ProductionPlanner`'s act, moving the run from `PRE_RUN_VERIFIED` to `IN_PRODUCTION`. Start converts every reserved allocation into consumption: for each entry, the lot's `reserved_qty_kg` decreases by the entry's quantity and its `consumed_qty_kg` increases by the same amount, leaving `available_qty_kg` unchanged; a lot left with zero available and zero reserved automatically moves to `DEPLETED` per §2.8. Start also stamps the line's `current_allergen_profile` with the revision's `allergen_profile`, and both the run's `version` and the line's `version` increment by one.

Completion records physical reality. A `ProductionPlanner` completes an `IN_PRODUCTION` run by supplying the actual `produced_cases` and the `scrapped_cases` (each zero or more). The completion first computes the run's cut plan: the batch yields a whole number of slabs — the revision's `batch_size_kg` divided by the line's `slab_weight_kg`, rounded down; each slab yields a whole number of sellable bars — the slab weight converted to grams, reduced by the four percent trim allowance, divided by the formula's `bar_weight_g`, and rounded down; total bars are the bars per slab multiplied by the slab count, with the per-slab floor applied before the multiplication because flooring only at the end would overstate the count and is not the specification; and the expected case count is the total bars divided by twelve bars per case, rounded down. The run's `produced_cases` must not exceed this expected count, else completion is rejected with `ERR_OUTPUT_EXCEEDS_CUT_PLAN` (HTTP 422) — the plant cannot sell more bars than the dough yields.

A successful completion performs several writes at once. The run's `release_status` moves from `NOT_READY` to `PENDING_QC` on the quality axis; its slot moves from `CONFIRMED` to `COMPLETED`; its `completed_utc` is stamped with the current logical clock; and its `version` increments. Completion also creates the run's **LotRelease** — exactly one per run — with `qc_disposition` `PENDING` and `decision` `PENDING`, carrying the computed `expected_cases` and the computed `yield_variance_pct`: the difference between `produced_cases` and `planned_cases`, divided by `planned_cases`, expressed as a percentage, and rounded half-up to two decimal places.

Cancellation is available to the `ProductionPlanner` while the run is still `PLANNED` or `SCHEDULED`. Cancelling a `PLANNED` run releases all of its reservations, decrementing each affected lot's `reserved_qty_kg`, and stamps `cancel_reason` `OPERATOR_CANCEL`. Cancelling a `SCHEDULED` run does the same and additionally moves its slot from `CONFIRMED` to `RELEASED` and its changeover event to `CANCELLED` unless that event already rests in the terminal `VALIDATED` state. Cancellation is terminal on the production axis; recall from §3.2 that the ingredient-shortage cascade performs a related but distinct automatic move, returning a `SCHEDULED` run to `PLANNED` with `cancel_reason` `INGREDIENT_SHORTAGE` rather than cancelling it.

Retain samples anchor the finished lot's traceability. A `QualityManager` registers a retain sample against a `COMPLETED` run, supplying the storage `bin_id`, the `cases_count` retained (greater than zero and no more than the run's `produced_cases`), and a `retain_until_utc`. The retain period must extend at least 30 days past the run's `completed_utc`; a shorter period is rejected with `ERR_RETAIN_PERIOD_TOO_SHORT` (HTTP 422). Retain samples are registered in `STORED` status and remain `STORED`; only `STORED` samples count toward the release gate. Each registration recomputes the lot release's `retain_cases_stored`, the sum of `cases_count` over the run's stored samples. The run's retain samples can be listed and filtered by `status`, and its lot release can be read back as a zero-or-one-element listing.

QC measurement and the release decision are split across two roles by segregation of duties. A `LabTechnician` records the QC disposition, supplying `qc_disposition` as `PASSED` or `FAILED` while the release's `qc_disposition` is still `PENDING`, and the release stamps `qc_recorded_by` with the technician's `X-User-ID`. The `QualityManager` then decides the lot. A decision of `RELEASED` from `decision` `PENDING` enforces its four guards in order: the decider's `X-User-ID` must differ from `qc_recorded_by` (`ERR_SOD_VIOLATION`, HTTP 422); `retain_cases_stored` must be at least one (`ERR_RETAIN_SAMPLE_REQUIRED`, HTTP 422); the absolute value of `yield_variance_pct` must be no greater than 5.00 percent, with exactly 5.00 passing (`ERR_YIELD_VARIANCE_EXCEEDED`, HTTP 422); and `qc_disposition` must be `PASSED` (`ERR_QC_NOT_PASSED`, HTTP 422). A release decision moves the run's `release_status` to `RELEASED`, stamps `decided_by`, recomputes the agreement's `produced_cases_current_quarter` and `shortfall_cases` per §3.3, and increments the `version` of the lot release, the run, and the agreement by one each. A decision of `HOLD_REWORK` from `PENDING` requires only the segregation-of-duties guard and moves the run's `release_status` to `HOLD_REWORK`, stamping `decided_by` and incrementing the release's and run's `version`. A decision of `SCRAPPED` from `PENDING` likewise requires the segregation-of-duties guard and moves the run's `release_status` to `SCRAPPED`. When rework is abandoned, a `SCRAPPED` decision is also permitted directly from `HOLD_REWORK`, moving the run's `release_status` to `SCRAPPED` and incrementing both versions. Both `RELEASED` and `SCRAPPED` decisions are terminal.

### 3.9. Shelf-Life Studies and Texture Projection

Shelf life is proven in the stability chamber, one study per claimed position. A `LabTechnician` opens a shelf-life study by naming the `revision_id` — which must reference an `APPROVED` revision whose parent formula is still `ACTIVE`, an archived formula failing with `ERR_FORMULA_ARCHIVED` — plus the `chamber_id`, the `shelf_position` within the chamber, the study's `start_utc`, the labeled `expiry_utc` (strictly later than the start), the `hardness_limit_n` ceiling on acceptable texture hardness in newtons (greater than zero), and optionally the `pull_interval_days` between texture pulls (at least one day, defaulting to seven). Chamber capacity is positional: at most one `ACTIVE` study may occupy a given chamber-and-shelf pair, and occupancy is measured over the closed interval from `start_utc` through `expiry_utc`, so a new study whose start exactly equals another active study's expiry still collides and is rejected with `ERR_CHAMBER_POSITION_OCCUPIED` (HTTP 409). A new study begins `ACTIVE`. The studies beneath a revision can be listed from the revision's perspective.

Texture is measured in pulls. A `LabTechnician` records a pull against an `ACTIVE` study, supplying the measured `hardness_n` in newtons (greater than zero) and the `recorded_utc` instant the reading was taken. Each pull records its parent in `study_id`, receives a 0-based `pull_index` assigned in creation order within its study, and a computed `due_utc`: the study's `start_utc` plus `pull_index` times the `pull_interval_days`. The recording window is bounded on both sides — `recorded_utc` may not lie in the future relative to the logical clock, and may not be later than two days of grace after `due_utc`; a recording outside the window is rejected with `ERR_PULL_WINDOW_MISSED` (HTTP 422). A pull is `RECORDED` at creation; a due-but-unrecorded pull becomes `MISSED` once the logical clock advances past its grace window, an evaluation performed whenever the clock is set and again at the next record attempt against the study.

Every recorded pull recomputes the study's `projected_hardness_at_expiry_n`, which is null until the first recording. With exactly one recorded pull, the projection is that pull's `hardness_n`. With two or more, the study's recorded pulls are ordered chronologically by `recorded_utc` with ties broken by `pull_index`; the growth rate is the change in hardness between the first and last recorded pulls divided by the elapsed days between their two readings, counted fractionally; and the projection is the first pull's hardness plus that rate multiplied by the study's full shelf length — the fractional day span from `start_utc` to `expiry_utc` — rounded half-up to two decimal places. The failure rule is strict: the study automatically moves from `ACTIVE` to `FAILED` the moment a recorded pull pushes the projection strictly greater than `hardness_limit_n`, while a projection exactly equal to the limit passes. Conversely, when a clock setting carries the logical clock past `expiry_utc`, an `ACTIVE` study whose projection is at or under the limit — or on which no pull has yet been recorded — automatically moves to `COMPLETED`. A `LabTechnician` may also terminate an `ACTIVE` study outright, moving it to `TERMINATED`. All three of `COMPLETED`, `FAILED`, and `TERMINATED` are terminal. The current projection can also be read directly, answering with the study's `projected_hardness_at_expiry_n`, the count of recorded pulls used in `pulls_used`, and a `will_fail` flag indicating whether the projection currently exceeds the limit. The study's pulls can be listed in the usual way.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including state-transition actions and updates to a resource's own fields — return `200 OK`. Request payloads, response payloads, and side effects are specified per workflow in §3; this table is the address book, not the contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/mfg/suppliers` | Register a supplier | PlantAdmin |
| GET | `/mfg/suppliers` | List suppliers | PlantAdmin, FormulationScientist, QualityManager, ProductionPlanner, LabTechnician |
| GET | `/mfg/suppliers/{id}` | Read one supplier | PlantAdmin, FormulationScientist, QualityManager, ProductionPlanner, LabTechnician |
| PATCH | `/mfg/suppliers/{id}` | Update supplier qualification status / allergens | PlantAdmin |
| POST | `/mfg/ingredients` | Register an ingredient | PlantAdmin |
| GET | `/mfg/ingredients` | List ingredients | PlantAdmin, FormulationScientist, QualityManager, ProductionPlanner, LabTechnician |
| GET | `/mfg/ingredients/{id}` | Read one ingredient | PlantAdmin, FormulationScientist, QualityManager, ProductionPlanner, LabTechnician |
| POST | `/mfg/ingredient-lots` | Receive an ingredient lot into QUARANTINE | PlantAdmin |
| GET | `/mfg/ingredient-lots` | List/filter ingredient lots | PlantAdmin, FormulationScientist, QualityManager, ProductionPlanner, LabTechnician |
| GET | `/mfg/ingredient-lots/{id}` | Read one ingredient lot | PlantAdmin, FormulationScientist, QualityManager, ProductionPlanner, LabTechnician |
| POST | `/mfg/ingredient-lots/{id}/release` | QC release a quarantined lot | QualityManager |
| POST | `/mfg/ingredient-lots/{id}/reject` | Reject a lot; cascades reservation release, readiness recompute, de-schedule | QualityManager |
| POST | `/mfg/customers` | Register a brand customer | PlantAdmin |
| GET | `/mfg/customers` | List brand customers | PlantAdmin, FormulationScientist, QualityManager, ProductionPlanner, LabTechnician |
| GET | `/mfg/customers/{id}` | Read one brand customer | PlantAdmin, FormulationScientist, QualityManager, ProductionPlanner, LabTechnician |
| POST | `/mfg/agreements` | Create a co-manufacturing agreement (NEGOTIATION) | PlantAdmin |
| GET | `/mfg/agreements` | List agreements; BrandCustomerRep must pass own customer_id | PlantAdmin, ProductionPlanner, QualityManager, BrandCustomerRep |
| GET | `/mfg/agreements/{id}` | Read one agreement incl. computed quarter rollup | PlantAdmin, ProductionPlanner, QualityManager, BrandCustomerRep |
| POST | `/mfg/agreements/{id}/activate` | NEGOTIATION → ACTIVE | PlantAdmin |
| POST | `/mfg/agreements/{id}/suspend` | ACTIVE → SUSPENDED | PlantAdmin |
| POST | `/mfg/agreements/{id}/resume` | SUSPENDED → ACTIVE | PlantAdmin |
| POST | `/mfg/agreements/{id}/terminate` | ACTIVE or SUSPENDED → TERMINATED (terminal) | PlantAdmin |
| GET | `/mfg/agreements/{id}/quote` | Tiered pricing quote for a case volume under the agreement's pricing mode | PlantAdmin, ProductionPlanner, BrandCustomerRep |
| POST | `/mfg/formulas` | Create a formula for a brand customer | FormulationScientist, BrandCustomerRep |
| GET | `/mfg/formulas` | List formulas; BrandCustomerRep must pass own customer_id | PlantAdmin, FormulationScientist, QualityManager, ProductionPlanner, LabTechnician, BrandCustomerRep |
| GET | `/mfg/formulas/{id}` | Read one formula incl. computed approved_revision_id | PlantAdmin, FormulationScientist, QualityManager, ProductionPlanner, LabTechnician, BrandCustomerRep |
| POST | `/mfg/formulas/{id}/revisions` | Create a DRAFT revision of the formula | FormulationScientist |
| GET | `/mfg/formulas/{id}/revisions` | List revisions of a formula | PlantAdmin, FormulationScientist, QualityManager, ProductionPlanner, LabTechnician, BrandCustomerRep |
| GET | `/mfg/revisions/{id}` | Read one revision incl. label/composite protein | PlantAdmin, FormulationScientist, QualityManager, ProductionPlanner, LabTechnician, BrandCustomerRep |
| POST | `/mfg/revisions/{id}/submit` | DRAFT → SUBMITTED | FormulationScientist |
| POST | `/mfg/revisions/{id}/verify-nutrition` | SUBMITTED → NUTRITION_VERIFIED; computes LABEL protein | QualityManager |
| POST | `/mfg/revisions/{id}/send-claim-review` | NUTRITION_VERIFIED → CLAIM_REVIEW | FormulationScientist |
| POST | `/mfg/revisions/{id}/approve` | CLAIM_REVIEW → APPROVED; CASCADE-SUPERSEDE | QualityManager |
| POST | `/mfg/revisions/{id}/reject-back` | CLAIM_REVIEW → DRAFT (cycle) | QualityManager |
| GET | `/mfg/revisions/{id}/shelf-life-studies` | List shelf-life studies of a revision | PlantAdmin, FormulationScientist, QualityManager, LabTechnician |
| GET | `/mfg/revisions/{id}/claim-reviews` | List claim reviews of a revision | PlantAdmin, FormulationScientist, QualityManager, BrandCustomerRep |
| POST | `/mfg/lines` | Register a slab/form/cut line | PlantAdmin |
| GET | `/mfg/lines` | List lines | PlantAdmin, FormulationScientist, QualityManager, ProductionPlanner, LabTechnician |
| GET | `/mfg/lines/{id}` | Read one line | PlantAdmin, FormulationScientist, QualityManager, ProductionPlanner, LabTechnician |
| GET | `/mfg/lines/{id}/slots` | List slots on a line | PlantAdmin, ProductionPlanner, QualityManager |
| GET | `/mfg/lines/{id}/changeovers` | List changeover events on a line | PlantAdmin, ProductionPlanner, QualityManager, LabTechnician |
| GET | `/mfg/lines/{id}/day-availability` | Computed per-day occupancy for a UTC calendar day | PlantAdmin, ProductionPlanner |
| GET | `/mfg/slots/{id}` | Read one line slot | PlantAdmin, ProductionPlanner, QualityManager |
| POST | `/mfg/production-runs` | Create a production run (PLANNED) against an APPROVED revision and ACTIVE agreement; reserves ingredients FIFO; OCC on the agreement | ProductionPlanner |
| GET | `/mfg/production-runs` | List/filter production runs; BrandCustomerRep scoped to own customer via the agreement | PlantAdmin, FormulationScientist, QualityManager, ProductionPlanner, LabTechnician, BrandCustomerRep |
| GET | `/mfg/production-runs/{id}` | Read one run | PlantAdmin, FormulationScientist, QualityManager, ProductionPlanner, LabTechnician, BrandCustomerRep |
| POST | `/mfg/production-runs/{id}/schedule` | Schedule the run: creates LineSlot + ChangeoverEvent; OCC on the line | ProductionPlanner |
| POST | `/mfg/production-runs/{id}/verify-pre-run` | SCHEDULED → PRE_RUN_VERIFIED; composite substantiation + sweetener top-up | QualityManager |
| POST | `/mfg/production-runs/{id}/start` | PRE_RUN_VERIFIED → IN_PRODUCTION; consumes reservations; sets line allergen profile | ProductionPlanner |
| POST | `/mfg/production-runs/{id}/complete` | IN_PRODUCTION → COMPLETED; creates LotRelease; release_status → PENDING_QC | ProductionPlanner |
| POST | `/mfg/production-runs/{id}/cancel` | PLANNED or SCHEDULED → CANCELLED; releases reservations/slot/changeover | ProductionPlanner |
| GET | `/mfg/production-runs/{id}/slots` | List the run's slot (0..1) | PlantAdmin, ProductionPlanner, QualityManager |
| GET | `/mfg/production-runs/{id}/changeovers` | List changeover events where the run is from_run or to_run | PlantAdmin, ProductionPlanner, QualityManager, LabTechnician |
| GET | `/mfg/production-runs/{id}/retain-samples` | List retain samples of the run | PlantAdmin, QualityManager, LabTechnician |
| GET | `/mfg/production-runs/{id}/lot-release` | Read the run's lot release (0..1 array) | PlantAdmin, QualityManager, LabTechnician |
| POST | `/mfg/production-runs/{id}/retain-samples` | Register a retain sample for a COMPLETED run | QualityManager |
| GET | `/mfg/changeovers/{id}` | Read one changeover event | PlantAdmin, ProductionPlanner, QualityManager, LabTechnician |
| POST | `/mfg/changeovers/{id}/log-cleaning` | PENDING or FAILED → CLEANING_LOGGED (re-clean loop) | ProductionPlanner |
| POST | `/mfg/changeovers/{id}/record-swab` | CLEANING_LOGGED → SWAB_RECORDED (SWAB_VALIDATE only) | LabTechnician |
| POST | `/mfg/changeovers/{id}/validate` | CLEANING_LOGGED or SWAB_RECORDED → VALIDATED; swab limit + SoD guards | QualityManager |
| POST | `/mfg/changeovers/{id}/fail` | SWAB_RECORDED → FAILED | QualityManager |
| POST | `/mfg/shelf-life-studies` | Open a shelf-life study for an APPROVED revision; closed-interval chamber-position capacity | LabTechnician |
| GET | `/mfg/shelf-life-studies/{id}` | Read one study incl. computed projection | PlantAdmin, FormulationScientist, QualityManager, LabTechnician |
| POST | `/mfg/shelf-life-studies/{id}/terminate` | ACTIVE → TERMINATED | LabTechnician |
| POST | `/mfg/shelf-life-studies/{id}/pulls` | Record a texture pull; recomputes hardness projection; may auto-FAIL the study | LabTechnician |
| GET | `/mfg/shelf-life-studies/{id}/pulls` | List pulls of a study | PlantAdmin, QualityManager, LabTechnician |
| GET | `/mfg/shelf-life-studies/{id}/projection` | Computed read of the hardness projection | PlantAdmin, QualityManager, LabTechnician |
| GET | `/mfg/lot-releases/{id}` | Read one lot release | PlantAdmin, QualityManager, LabTechnician |
| POST | `/mfg/lot-releases/{id}/record-qc` | Record QC disposition (PENDING → PASSED or FAILED) | LabTechnician |
| POST | `/mfg/lot-releases/{id}/decide` | Decide the lot: RELEASED, HOLD_REWORK, or SCRAPPED; SoD + retain + yield + QC gates; drives run release_status and the agreement rollup | QualityManager |
| POST | `/mfg/claim-reviews` | Submit a claim review for a revision claim | FormulationScientist, BrandCustomerRep |
| GET | `/mfg/claim-reviews/{id}` | Read one claim review | PlantAdmin, FormulationScientist, QualityManager, BrandCustomerRep |
| POST | `/mfg/claim-reviews/{id}/start-review` | SUBMITTED → IN_REVIEW | QualityManager |
| POST | `/mfg/claim-reviews/{id}/approve` | IN_REVIEW → APPROVED; substantiation + disclaimer guards | QualityManager |
| POST | `/mfg/claim-reviews/{id}/request-revision` | IN_REVIEW → REVISION_REQUESTED | QualityManager |
| POST | `/mfg/claim-reviews/{id}/resubmit` | REVISION_REQUESTED → SUBMITTED (cycle) | FormulationScientist, BrandCustomerRep |
| POST | `/mfg/_clock/set_current_utc` | Test-driving logical clock; evaluates time-based transitions | PlantAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them in §2 and §3; this catalogue is the identifier reference only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_CUSTOMER_SCOPE` | 403 Forbidden |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_SUPPLIER_NOT_FOUND` | 404 Not Found |
| `ERR_FORMULA_NOT_FOUND` | 404 Not Found |
| `ERR_REVISION_NOT_FOUND` | 404 Not Found |
| `ERR_INGREDIENT_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_CHANGEOVER_NOT_FOUND` | 404 Not Found |
| `ERR_STUDY_NOT_FOUND` | 404 Not Found |
| `ERR_RELEASE_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_REVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_ENUM_VALUE` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_TERMINAL_STATE_LOCKED` | 409 Conflict |
| `ERR_ALLERGEN_SEGREGATION_VIOLATION` | 422 Unprocessable Entity |
| `ERR_LABEL_CLAIM_UNSUBSTANTIATED` | 422 Unprocessable Entity |
| `ERR_COMPOSITE_CLAIM_UNSUBSTANTIATED` | 422 Unprocessable Entity |
| `ERR_CHANGEOVER_NOT_VALIDATED` | 422 Unprocessable Entity |
| `ERR_SWAB_PPM_EXCEEDS_LIMIT` | 422 Unprocessable Entity |
| `ERR_SOD_VIOLATION` | 422 Unprocessable Entity |
| `ERR_RETAIN_SAMPLE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_RETAIN_PERIOD_TOO_SHORT` | 422 Unprocessable Entity |
| `ERR_DISCLAIMER_REQUIRED` | 422 Unprocessable Entity |
| `ERR_SCHEDULE_IN_PAST` | 422 Unprocessable Entity |
| `ERR_SLOT_OVERLAP` | 409 Conflict |
| `ERR_SLOT_CHANGEOVER_BUFFER_VIOLATION` | 409 Conflict |
| `ERR_CHAMBER_POSITION_OCCUPIED` | 409 Conflict |
| `ERR_PULL_WINDOW_MISSED` | 422 Unprocessable Entity |
| `ERR_REVISION_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_AGREEMENT_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_CUSTOMER_SUSPENDED` | 422 Unprocessable Entity |
| `ERR_SUPPLIER_NOT_QUALIFIED` | 422 Unprocessable Entity |
| `ERR_INGREDIENT_DISCONTINUED` | 422 Unprocessable Entity |
| `ERR_FORMULA_ARCHIVED` | 422 Unprocessable Entity |
| `ERR_CLAIM_REVIEW_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_LOT_CODE` | 409 Conflict |
| `ERR_OUTPUT_EXCEEDS_CUT_PLAN` | 422 Unprocessable Entity |
| `ERR_SWAB_NOT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_INGREDIENT_SHORTAGE` | 422 Unprocessable Entity |
| `ERR_YIELD_VARIANCE_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_QC_NOT_PASSED` | 422 Unprocessable Entity |
| `ERR_MOQ_SHORTFALL` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
