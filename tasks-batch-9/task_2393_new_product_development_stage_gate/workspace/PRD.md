# NPD Stage-Gate API — Product Requirements Document

## 1. Introduction

Consumer packaged goods innovation teams lose more money to badly governed pipelines than to bad ideas. A concept that was never screened against a financial hurdle consumes pilot plant time; a launch is locked before regulatory clears the on-pack claims; a retailer reset window is double-booked because two account managers worked from stale slot counts; a business case is quietly rewritten after the gate that approved it, so post-launch attainment is measured against a plan nobody signed. This API exists to make each of those failures impossible by construction rather than by process discipline.

The system it describes is a stage-gate spine for new product development, spanning idea intake and screening, consumer concept testing, volume forecasting and business-case financials, formulation and packaging development with pilot plant scale-up and shelf-life stability testing, cross-functional gate reviews with go/no-go authority, regulatory and label clearance, customer sell-in against retailer shelf reset windows, a launch date lock, and post-launch performance tracking that ends in a continue, fix or discontinue verdict. Two things make the model unusual. First, every project carries **two independent status tracks on the same record** — a development track and a commercial track — which advance on different triggers and are only bound together at the launch date lock and at launch execution. Second, governance is enforced as **segregation of duties over opaque actor identifiers**: the person who owns a project may not vote at its gates, the person who submits a checklist item may not approve it, and a chair who cast a ballot may not close the review that ballot decided.

Everything temporal in the system is measured against a server-held logical clock rather than wall time, so that lead-time rules, reset window containment and study durations are all deterministically testable. The remainder of this document specifies the global contracts every endpoint honours (§2), the business logic and workflow rules that make up the pipeline (§3), the endpoint surface (§4), and the complete error catalogue (§5).

## 2. Global Specifications & System-Wide Principles

### 2.1. Actors, Authentication and Segregation of Duties

Every request — reads included — must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity that user is acting in. If either header is absent the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401), and this check runs ahead of everything else, including path resolution, so an unauthenticated request naming a non-existent resource still answers 401 rather than 404. When both headers are present but the declared role is not among the roles authorised for the target operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403); this too precedes path resolution, so a wrong-role request against an unknown id answers 403, not 404.

Seven roles exist, spelled exactly: `PortfolioAdmin`, `InnovationLead`, `GateChair`, `FunctionalReviewer`, `RegulatoryApprover`, `RnDLead`, and `SalesAccountManager`. Every one of the seven may call every read endpoint. Write authority is partitioned: `PortfolioAdmin` governs the configuration roots (stage gates, retailers, reset windows, pilot lines), the logical clock, condition expiry and post-launch reporting; `InnovationLead` owns project intake, consumer testing, business cases and forecast lines, and label drafting; `GateChair` holds go/no-go authority — screening, scheduling, opening and closing reviews, condition clearing, waivers, the launch date lock and launch execution; `FunctionalReviewer` decides submitted checklist items and casts ballots; `RegulatoryApprover` decides label approvals and may also occupy the `REGULATORY` gate seat; `RnDLead` owns formulation revisions, pilot runs and stability studies; `SalesAccountManager` owns trade presentation booking, presentation, outcome recording and withdrawal. Checklist submission is deliberately broad: `InnovationLead`, `RnDLead`, `FunctionalReviewer` and `SalesAccountManager` may all submit evidence.

**Actor identity is opaque throughout.** When `X-User-Role` is `PortfolioAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it to any row's `id`. The same holds for `InnovationLead`, `GateChair`, `FunctionalReviewer`, `RegulatoryApprover`, `RnDLead` and `SalesAccountManager` — for all seven roles, `X-User-ID` is an opaque string, never a foreign key. The server does, however, *record* it in five places and then compare recorded strings against each other: `owner_user_id` on `InnovationProject` (captured from the `InnovationLead` who created the project), `voter_user_id` on `GateVote`, `chair_user_id` on `GateReview` (captured from the `GateChair` who closed it), `submitted_by_user_id` and `decided_by_user_id` on `Deliverable`, and `decided_by_user_id` on `LabelApproval`. None of these fields is a foreign key into a user table; they exist purely so the three segregation-of-duties rules below can be evaluated.

Those three rules are:

- A checklist item's decider may not be its submitter. If the acting `X-User-ID` equals the item's `submitted_by_user_id`, the decision is rejected with `ERR_SELF_APPROVAL_FORBIDDEN` (403).
- A project's owner may not vote at its own gate. If the acting `X-User-ID` equals the project's `owner_user_id`, the ballot is rejected with `ERR_OWNER_CANNOT_VOTE` (403).
- A chair who voted may not close the review. If the acting `X-User-ID` already appears as the `voter_user_id` of any `GateVote` on the review being closed, the close is rejected with `ERR_CHAIR_CANNOT_VOTE_AND_CLOSE` (403).

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

### 2.3. Pagination and List Ordering

Collection endpoints are paginated by two query parameters. `limit` caps the number of rows returned; it defaults to 10, may not be below 1 and may not exceed 100. `offset` is the number of rows to skip and defaults to 0. Both `limit` and `offset` are echoed in the `meta` object alongside `total_count` (the number of rows matching the filters before pagination) and `has_more` (true when rows remain beyond the current page).

Unless a specific list says otherwise, rows are ordered by `created_at` ascending. The exceptions are pinned, and `id` is never an ordering key anywhere in the system:

- The stage-gate configuration list is ordered by `created_at` **descending** — newest configuration first. It is the only descending-by-creation list in the API.
- Concept tests for a project are ordered by `fielded_at` descending, then `created_at` ascending.
- A retailer's reset windows are ordered by `window_start` ascending, then `created_at` ascending.
- Pilot runs are ordered by `window_start` ascending, then `created_at` ascending.
- A formulation's stability studies are ordered by `start_at` ascending, then `created_at` ascending.
- Trade presentations are ordered by `scheduled_at` ascending, then `created_at` ascending.
- A project's formulation revisions are ordered by `revision` ascending.
- A project's post-launch periods are ordered by `period_index` ascending.
- Checklist items are ordered by `created_at` ascending, then `deliverable_type` ascending.

List endpoints also accept optional equality filters drawn from the listed entity's own fields. Stage gates filter on `category` and `gate_number`; retailers and pilot lines on `channel` and `allergen_regime` respectively; reset windows on `category`; projects on `dev_status`, `commercial_status`, `category` and `shelf_reset_window_id`; business cases on `status` and `variant_mode`; checklist items on `project_id`, `gate_id`, `prerequisite_deliverable_id`, `status` and `owner_function`; gate reviews on `project_id`, `gate_id` and `status`; formulations and stability studies on `status`; pilot runs on `formulation_id`, `pilot_line_id` and `status`; label approvals on `project_id`, `formulation_id` and `status`; trade presentations on `project_id`, `retailer_id`, `shelf_reset_window_id` and `status`.

### 2.4. Resource Identity, Audit Fields and the Logical Clock

Every stored resource is addressed by an `id` that the server mints as a UUID. Identifiers carry no type prefix and clients never supply them. Alongside `id`, every entity in this system also carries `created_at`, `updated_at` and `version`: `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits, and `version` is an integer that starts at 1 on insert and increments by one on every accepted write to that row. There is exactly one exception — `GateVote` is immutable once cast and therefore carries only `id` and `created_at`; it has neither `updated_at` nor `version`.

Derived-field maintenance counts as a write. When the server recomputes `development_budget_committed_usd`, `launch_readiness_pct`, `authorized_acv_pct`, `next_gate_number`, `recycle_count`, `open_gate_conditions` or `post_launch_decision` on a project, or `booked_slot_count` on a reset window, or `best_pilot_yield_pct` on a formulation, that row's `updated_at` is refreshed and its `version` increments even though no client sent a request naming that row directly. This is what makes the optimistic-concurrency contract of §2.6 meaningful.

Time is not read from the host. The system holds a **logical clock**, referred to throughout as the current instant, which begins at `2026-08-01T00:00:00Z` on a freshly started system and changes only when a `PortfolioAdmin` calls the clock-setting capability with a `to_iso8601` value; the response reports the new `current_utc`. Every lead-time comparison, window containment test, due-date check and "has this instant been reached yet" precondition in §3 is evaluated against that logical instant.

### 2.5. Order of Rejection

Many operations can fail several ways at once. The server always evaluates checks in the following thirteen bands and answers with the **first** violated rule, so the reported error is a deterministic function of request and state rather than of implementation order.

1. **Authentication** — both headers present, else `ERR_UNAUTHENTICATED` (401).
2. **Role authorisation** — the declared role is authorised for the operation, else `ERR_UNAUTHORIZED` (403).
3. **Path existence** — every identifier in the URL resolves to a stored row, resolved outer to inner, so a nested path with two unknown identifiers reports the outer resource first. Each resource family has its own 404 code: `ERR_PROJECT_NOT_FOUND` for a project, `ERR_STAGE_GATE_NOT_FOUND` for a gate configuration, `ERR_GATE_REVIEW_NOT_FOUND` for a review, `ERR_DELIVERABLE_NOT_FOUND` for a checklist item, `ERR_BUSINESS_CASE_NOT_FOUND` for a business case, `ERR_FORMULATION_NOT_FOUND` for a formulation revision, `ERR_PILOT_LINE_NOT_FOUND` for a pilot line, `ERR_PILOT_RUN_NOT_FOUND` for a pilot run, `ERR_SHELF_LIFE_STUDY_NOT_FOUND` for a stability study, `ERR_LABEL_APPROVAL_NOT_FOUND` for a label approval, `ERR_RETAILER_NOT_FOUND` for a retailer, `ERR_RESET_WINDOW_NOT_FOUND` for a reset window, and `ERR_PRESENTATION_NOT_FOUND` for a trade presentation.
4. **Request shape** — the body parses, required fields are present, enum values are legal, numbers lie inside their declared ranges and datetimes are ISO 8601. Otherwise `ERR_INVALID_REQUEST` (400). Shape validation runs before any body-borne foreign key is resolved, so a request that both omits a required field and names a non-existent parent answers 400.
5. **Body foreign-key existence** — every identifier supplied in the body resolves, checked left to right in the order the fields are declared for that operation. Answers the matching 404 code. This band applies to gate-review scheduling, checklist creation and prerequisite setting, pilot-run booking, label drafting, trade-presentation booking and the launch date lock.
6. **State** — the subject row and its governing parents admit the requested transition, else the entity's `ERR_..._INVALID_STATE` code (409). State is checked **before** optimistic concurrency, so a stale version supplied against an already-terminal row reports the state error rather than 412.
7. **Optimistic concurrency** — the supplied expected parent version matches the stored one, else 412 (see §2.6). Concurrency runs after state and before every business rule, so a stale version outranks a budget overrun or a referential violation raised by the same request.
8. **Segregation of duties** — the three rules of §2.1, answering 403. Because this band follows state, a decide attempted on a `PENDING` checklist item reports the state error rather than the self-approval error.
9. **Business safety** (409) — gate sequencing, single-open-review, unresolved conditions, quorum, one ballot per function, prerequisite satisfaction, prerequisite acyclicity, the regulatory waiver prohibition, duplicate checklist types, duplicate channel lines, configuration uniqueness, pilot line window conflicts and reset window capacity.
10. **Business referential integrity** (409) — cross-aggregate relationship rules where both rows exist but do not belong together: reset window ownership, category match, channel-in-forecast, formulation-to-project ownership, label clearance, locked business case and period sequencing.
11. **Business temporal rules** (409) — presentation lead time, launch date containment, lock lead time, launch date reached, presentation due, pilot window open, timepoint chronology and condition deadlines.
12. **Business constraints** (422) — checklist completeness, gate readiness floor, accepted-versus-proposed SKU counts, launch readiness completeness and the unsupported-claims requirement.
13. **Fiscal constraints** (422) — the development budget cap and the business-case financial hurdles. This is the lowest band, so a stale formulation version or a pilot line window conflict is always reported ahead of a budget overrun.

Within band 9, gate-review opening evaluates gate sequencing first, then the single-open-review rule, then the unresolved-conditions rule. Within bands 12 and 13, a passing gate close evaluates checklist completeness first, then the readiness floor, then the financial hurdles — so an incomplete checklist masks a low readiness index, and a low readiness index masks a missed hurdle. At the launch date lock, window containment is evaluated before lock lead time, so a date that is both outside the window and too soon reports the containment error.

### 2.6. Optimistic Concurrency on Projects and Formulation Revisions

Three write operations mutate state that other in-flight work depends on, and each of them therefore requires the client to declare which version of the parent it last observed. The declared field is **not optional**; omitting it is a shape violation answering `ERR_INVALID_REQUEST`. No other endpoint in this API accepts a version field, and none may be added.

- Opening a business case under a project requires `expected_project_version` in the body, carrying the client's last observed `InnovationProject.version`. If it does not equal the project's stored `version` at validation time, the create is rejected with `ERR_PROJECT_VERSION_CONFLICT` (HTTP 412). Because a business case supersedes the project's previous non-locked case, a client working from a version read before an intervening project write would otherwise discard a case it never saw.
- Creating the next formulation revision under a project likewise requires `expected_project_version`, and a mismatch against the stored `InnovationProject.version` is rejected with `ERR_PROJECT_VERSION_CONFLICT` (HTTP 412). This is the more consequential of the two: an accepted revision supersedes the previous formulation, cancels its live pilot runs, abandons its live stability studies, invalidates its label clearance and can slip a locked launch date. A rejected write leaves the prior formulation, its label approvals and the launch lock completely untouched; the cascade only ever runs inside an accepted write.
- Opening a stability study under a formulation requires `expected_formulation_version` in the body, carrying the client's last observed `Formulation.version`. A mismatch against the stored `Formulation.version` is rejected with `ERR_FORMULATION_VERSION_CONFLICT` (HTTP 412). A study may only be opened against the revision the caller actually read, and note that `Formulation.version` advances on every accepted write to the formulation row — including the pilot-run and study cascades that update `status` and `best_pilot_yield_pct` — so a caller that books a pilot run and then opens a study must re-read the revision in between.

Where any ordering fallback is needed among rows sharing a timestamp, resolve by `created_at` ascending. `id` is never used to order or to break ties.

### 2.7. Numeric Precision and Rounding

Every computed number in this system is produced by **round half up** — ties away from zero — at a fixed number of decimal places, and rounding is applied at each step named in §3 rather than only once at the end. The scales are:

- Money, percentages, scores and indices: **2 decimal places**. This covers `screening_score`, `concept_score`, `readiness_index`, `deliverable_completeness_pct`, `launch_readiness_pct`, `authorized_acv_pct`, `yield_pct`, `development_budget_committed_usd`, `best_pilot_yield_pct`, `min_quality_score`, `plan_units_per_period`, all three attainment percentages, and every `_usd` and `_pct` field on a business case.
- Unit prices: **4 decimal places** — `list_price_usd`, `avg_list_price_usd`, `cogs_per_unit_usd` and `unit_cost_usd`.
- Volumes: whole numbers — `annual_units`, `line_units`, `actual_units`, `planned_units`, `store_count`.
- One intermediate is carried at higher precision before being capped: the normalised margin criterion inside idea screening is rounded to 4 decimals and only then capped (see §3.2).

`gross_margin_usd`, `gross_margin_pct` and `actual_gross_margin_usd` may legitimately be negative; nothing clamps them at zero. Percentages that represent shares of a whole — `launch_readiness_pct`, `authorized_acv_pct`, `readiness_index` — are capped at `100.00` where §3 says so, and never otherwise.

### 2.8. The Two Status Tracks and Which Operations Each Admits

An `InnovationProject` carries two enumerated state fields that evolve independently on the same row. The development track, `dev_status`, moves through `IDEA`, `SCREENED`, `PILOT_QUALIFIED`, `LAUNCH_READY`, `LAUNCHED`, `IN_MARKET_FIX`, and terminates in `KILLED` or `DISCONTINUED`; it starts at `IDEA`. The commercial track, `commercial_status`, moves through `NOT_STARTED`, `SELL_IN_SCHEDULED`, `PRESENTED`, `AUTHORIZED`, `SELL_IN_REJECTED`, `LAUNCH_LOCKED`, `LOCK_SLIPPED`, and terminates in `SHIPPED`; it starts at `NOT_STARTED`. Neither track is a function of the other. They are bound together at exactly two moments: the launch date lock demands a specific pair, and launch execution advances both in a single request.

`ERR_PROJECT_INVALID_STATE` (409) is the answer whenever a project-scoped operation is attempted from a track state that does not admit it. The admitted sets are:

- Screening admits `dev_status` `IDEA` only.
- Business-case creation, formulation creation, checklist creation and gate-review scheduling admit `dev_status` in `IDEA`, `SCREENED`, `PILOT_QUALIFIED` or `LAUNCH_READY`.
- Trade-presentation booking admits `dev_status` in `PILOT_QUALIFIED`, `LAUNCH_READY`, `LAUNCHED` or `IN_MARKET_FIX`.
- The launch date lock admits `dev_status` `LAUNCH_READY` together with `commercial_status` in `AUTHORIZED` or `LOCK_SLIPPED`.
- Launch execution admits `dev_status` `LAUNCH_READY` together with `commercial_status` `LAUNCH_LOCKED`.
- Post-launch period reporting admits `dev_status` in `LAUNCHED` or `IN_MARKET_FIX`.

### 2.9. Cascade Discipline

Several single requests mutate many rows. Cascades are not best-effort: every secondary effect named in §3 is part of the same accepted write as the primary effect, and each mutated row refreshes its own `updated_at` and increments its own `version` per §2.4. Three cascades dominate the system and are described in full where they arise: the **kill cascade** driven by a vetoed gate decision (§3.6), the **depth-four supersede cascade** driven by a new formulation revision (§3.7), and the **slot-and-ACV release cascade** driven by presentation withdrawal or project termination (§3.8).

Two consequences deserve stating up front. First, `APPROVED` is *not* a terminal status for a checklist item: the regulatory clearance item is driven back to `PENDING` when the label describing the current formulation is invalidated. Second, a cascade may move the commercial track backwards — a locked launch date is released and `commercial_status` returns from `LAUNCH_LOCKED` to `LOCK_SLIPPED` when the formulation underneath it is superseded.

### 2.10. The Development Budget Ledger

Committed development spend is a **conserved quantity**, not a running total. `development_budget_committed_usd` on a project is, at every observable instant, exactly the sum of `committed_cost_usd` across that project's live pilot runs — those whose `status` is `SCHEDULED`, `RUNNING` or `COMPLETED` — plus `committed_cost_usd` across its live stability studies — those whose `status` is `ACTIVE`, `PASSED` or `FAILED` — rounded half up to two decimal places. A run or study belongs to the project through the formulation it hangs off.

Because the field is a sum over live contributors rather than an accumulator, releases are exact and drift-free: a run that moves to `CANCELLED` and a study that moves to `ABANDONED` both drop out of the basis, returning the field to precisely its pre-write value, which means the same cost can be committed again afterwards. A create that would push the post-write value above the project's `development_budget_cap_usd` is rejected with `ERR_DEV_BUDGET_EXCEEDED` (422); the boundary itself is permitted, so a write that lands the committed total exactly on the cap succeeds while one cent more does not.

### 2.11. Cross-Aggregate Referential Integrity

Four resource families are independent roots with no owning parent — `InnovationProject`, `StageGate`, `Retailer` and `PilotLine` — and the API therefore has no single URL prefix. The bindings between them are enforced as explicit relationship rules rather than as containment, and each yields 409 rather than 404 because both rows genuinely exist:

- A reset window named in a trade presentation must belong to the named retailer, else `ERR_WINDOW_RETAILER_MISMATCH`.
- A reset window's `category` must equal the project's `category`, else `ERR_WINDOW_CATEGORY_MISMATCH`. A beverage project cannot take a household reset slot. This rule guards both trade-presentation booking and the launch date lock.
- The retailer's `channel` must appear as the `channel` of some forecast line on the project's authoritative business case, else `ERR_CHANNEL_NOT_FORECAST`.
- A formulation named when drafting a label must belong to the project in the path, else `ERR_FORMULATION_PROJECT_MISMATCH`.

Two derived notions are used repeatedly and are defined once here. A project's **authoritative business case** is its most recently created case whose `status` is not `SUPERSEDED`; candidates are ordered by `created_at` ascending and the last is taken, and `id` is never consulted. A project's **current formulation** is the revision with the highest `revision` whose `status` is not `SUPERSEDED`.

### 2.12. Enumerations of Record

The following closed vocabularies are used throughout and any other value is a shape violation answering `ERR_INVALID_REQUEST`.

CPG categories: `BEVERAGE`, `SNACK`, `DAIRY`, `HOUSEHOLD`. Innovation types: `NEW_BRAND`, `LINE_EXTENSION`, `RENOVATION`. Cross-functional seats, used for both `owner_function` and a ballot's `function`: `R_AND_D`, `MARKETING`, `FINANCE`, `OPERATIONS`, `QUALITY`, `REGULATORY`, `SALES`. Ballot values: `APPROVE`, `APPROVE_WITH_CONDITIONS`, `REJECT`. Retail channels: `GROCERY`, `MASS`, `CLUB`, `CONVENIENCE`, `ECOMMERCE`. Research instruments (`test_type`): `MONADIC`, `SEQUENTIAL_MONADIC`, `IN_HOME_USE`. Volume derivation variants (`variant_mode`): `BOTTOM_UP`, `TOP_DOWN`. Case types (`case_type`): `PRELIMINARY`, `FINAL`. Allergen regimes: `NONE`, `DAIRY`, `NUT`, `GLUTEN`. Attainment bases: `CUMULATIVE`, `TRAILING`. Post-launch decisions: `CONTINUE`, `FIX`, `DISCONTINUE`. Screening outcomes (`screening_decision`): `PENDING`, `PASSED`, `REJECTED`. Stability verdicts: `PASS`, `FAIL`.

The ten checklist item types (`deliverable_type`) are `CONSUMER_CONCEPT_TEST`, `PRELIM_BUSINESS_CASE`, `FINAL_BUSINESS_CASE`, `PILOT_SCALE_UP_REPORT`, `SHELF_LIFE_REPORT`, `REGULATORY_CLEARANCE`, `MANUFACTURING_READINESS`, `DISTRIBUTION_READINESS`, `MARKETING_LAUNCH_PLAN` and `SALES_SELL_IN_PLAN`. The first six are **evidence types**, auto-approved by the transitions that produce their evidence; the last four are **readiness types**, submitted and decided by hand, and they alone drive `launch_readiness_pct`.

## 3. Business Logic & Workflows

### 3.1. Portfolio Configuration and Idea Intake

Before any project can move, a `PortfolioAdmin` populates the three configuration roots. A **stage gate** configuration is registered per category with a `gate_number`, a `category`, the `stage_from` development state a project must hold to convene it (`SCREENED` or `PILOT_QUALIFIED`), the `stage_to` state a passing decision moves it to (`PILOT_QUALIFIED` or `LAUNCH_READY`), the `required_deliverable_types` checklist that is auto-created when a project enters `stage_from`, a `quorum_size` of at least one ballot, the `veto_functions` whose rejection is fatal rather than merely recycling, and the four bars a passing decision must clear: `npv_hurdle_usd`, `payback_months_max`, `gross_margin_floor_pct` and `readiness_floor_index`. Gate numbering starts at 2 because gate 1 *is* the screening step, and the pair of `category` and `gate_number` must be unique — a second registration of the same pair is rejected with `ERR_DUPLICATE_RESOURCE`. The `required_deliverable_types` array may legitimately be empty and must contain no duplicates.

A **retailer** carries a unique `name`, the `channel` it trades in, an `acv_contribution_pct` between `0.00` and `100.00` describing the all-commodity-volume weight it adds when it authorises a project, and a `presentation_lead_days` count. Retailer names are unique, and a duplicate answers `ERR_DUPLICATE_RESOURCE`. Under a retailer, the admin opens **shelf reset windows**, each with a `category`, an inclusive `window_start`, an inclusive `window_end` strictly after it, and a `max_presentations` slot capacity of at least one. Each window maintains `booked_slot_count`, a conserved counter equal to the number of trade presentations against it whose `status` is `PLANNED`, `PRESENTED`, `DEFERRED` or `ACCEPTED`. A **pilot line** carries a `plant_name`, a `line_code` unique across all lines (duplicates answer `ERR_DUPLICATE_RESOURCE`), a base `changeover_buffer_minutes` between 0 and 1440, the `allergen_regime` currently set up on the line, and an informational `hourly_cost_usd`.

An `InnovationLead` intakes an idea by supplying a `name` of 1 to 120 characters, the owning `brand`, the `category`, the `project_type`, four rating inputs — `strategic_fit_score`, `consumer_need_score` and `category_attractiveness_score` each on a `0.00` to `10.00` scale, plus `target_gross_margin_pct` between `0.00` and `100.00` — and a `development_budget_cap_usd` of at least `0.00`. The acting user's opaque identifier is captured as `owner_user_id`, which is what later bars that same person from voting at the project's gates. A freshly intaken project has `dev_status` `IDEA`, `commercial_status` `NOT_STARTED`, `next_gate_number` 2, `screening_decision` `PENDING`, `screening_score` and `launch_date` and `shelf_reset_window_id` and `post_launch_decision` all null, `development_budget_committed_usd` `0.00`, `launch_readiness_pct` `0.00`, `authorized_acv_pct` `0.00`, `recycle_count` 0, and `open_gate_conditions` false.

### 3.2. Gate 1: Idea Screening

Screening is the only gate decided by a single actor rather than a ballot: a `GateChair` screens the idea, optionally attaching `screening_notes`, and the project's `dev_status` moves out of `IDEA` in one of two directions. The operation is admissible only from `IDEA`; from anywhere else it answers `ERR_PROJECT_INVALID_STATE`.

The score is a weighted blend of the four intake ratings. First the margin criterion is normalised: `target_gross_margin_pct` is divided by the reference target of 40 percent, multiplied by 100, rounded half up to four decimal places, and then capped at 100 — so a project targeting a 60 percent gross margin normalises to 100 rather than 150, and the extra ambition earns nothing. The three rating inputs are each rescaled from their 0-to-10 range onto a 0-to-100 range by multiplying by 10. Those four criterion values — strategic fit, consumer need, the normalised margin, and category attractiveness, in that order — are then combined under the weight vector chosen by `project_type`:

- `NEW_BRAND` weights them 0.30, 0.30, 0.25 and 0.15.
- `LINE_EXTENSION` weights them 0.30, 0.25, 0.30 and 0.15.
- `RENOVATION` weights them 0.20, 0.35, 0.25 and 0.20.

The four weighted terms are summed and the sum is rounded half up to two decimal places to give `screening_score`. Identical intake ratings therefore produce different scores under different innovation types, which is intentional: a line extension is judged more on margin, a renovation more on consumer need. The screening floor is `60.00`. When `screening_score` is at least `60.00`, `screening_decision` becomes `PASSED` and `dev_status` advances `IDEA → SCREENED`; a score one cent below the floor sets `screening_decision` to `REJECTED` and moves `dev_status` `IDEA → KILLED` instead. Both outcomes store `screening_score`.

Passing also builds the project's first checklist. The server locates the stage gate registered for the project's `category` with `gate_number` 2; if no such configuration exists the screening is rejected with `ERR_STAGE_GATE_NOT_FOUND`. It then creates one checklist item in status `PENDING` for each entry of that gate's `required_deliverable_types`, **in array order**, stamping each with the gate's `gate_id` and taking `owner_function` from the fixed type-to-function map: `CONSUMER_CONCEPT_TEST` and `MARKETING_LAUNCH_PLAN` belong to `MARKETING`; `PRELIM_BUSINESS_CASE` and `FINAL_BUSINESS_CASE` to `FINANCE`; `PILOT_SCALE_UP_REPORT` to `R_AND_D`; `SHELF_LIFE_REPORT` to `QUALITY`; `REGULATORY_CLEARANCE` to `REGULATORY`; `MANUFACTURING_READINESS` and `DISTRIBUTION_READINESS` to `OPERATIONS`; and `SALES_SELL_IN_PLAN` to `SALES`. Auto-creation is idempotent by pair: any combination of `gate_id` and `deliverable_type` that already exists on the project is skipped rather than duplicated. `next_gate_number` stays at 2, because gate 2 is now the gate to convene. On the killing branch no checklist is created at all.

### 3.3. Consumer Concept Testing

An `InnovationLead` records a consumer study against the project with a `test_type`, a `sample_size` of at least 1 respondent, a top-two-box `purchase_intent_top2_pct` and a `uniqueness_pct` (each between `0.00` and `100.00`), and the `fielded_at` date the study went into field.

Each study is scored the moment it is recorded. Purchase intent is weighted 0.60 and uniqueness 0.40; their weighted sum is then multiplied by a confidence multiplier chosen from the respondent count — `1.00` when `sample_size` is at least 300, `0.95` when `sample_size` is at least 100 but below 300, and `0.85` when `sample_size` is below 100 — and the product is rounded half up to two decimal places to give `concept_score`. The tier boundaries are inclusive at the bottom: 100 respondents earn the `0.95` multiplier while 99 earn only `0.85`, and 300 respondents earn the full `1.00`.

A project may hold several studies but only one counts. The `is_authoritative` flag is true for exactly one row per project: the study with the greatest `fielded_at`, and where several share that instant, the earliest created among them. Recording a newer study therefore clears `is_authoritative` on the studies it displaces. Only the authoritative study's `concept_score` feeds the gate readiness index of §3.6; a project with no study at all contributes `0.00` there.

Recording a study is also the evidence event for the `CONSUMER_CONCEPT_TEST` checklist item: any such item sitting in `PENDING` on the project moves `PENDING → APPROVED` in the same write, with `evidence_url` set to the literal string `system://auto-approved` and both `submitted_by_user_id` and `decided_by_user_id` left null — nobody submitted it and nobody decided it, the evidence produced it.

### 3.4. Business Cases, Channel Forecasts and Financial Hurdles

An `InnovationLead` opens a business case under a project, declaring `expected_project_version` per §2.6 alongside the `variant_mode` that selects how volume is derived, the `category_size_units_year` and `target_share_pct` used only by the top-down derivation, the `cogs_per_unit_usd` at four decimals, the one-time `slotting_fees_usd`, the up-front `capex_usd`, and the annual `discount_rate_pct`. The project's first case takes `case_type` `PRELIMINARY`; every later case takes `FINAL`. Opening a new case supersedes the project's previous case: a prior case in `DRAFT` moves `DRAFT → SUPERSEDED`, and a prior case in `COMPUTED` moves `COMPUTED → SUPERSEDED` — but only if it is not `LOCKED`. A `LOCKED` case is never superseded, which is precisely why raising a new case after a gate lock leaves the project without a locked authoritative case and blocks post-launch reporting (§3.9).

A case starts in `DRAFT` with `annual_units` 0, `gross_revenue_usd` `0.00`, `avg_list_price_usd` `0.0000` and every other financial output at `0.00`, `payback_months` at 0 and `trade_spend_rate_pct` at `0.00`. It acquires numbers only when channel forecast lines are added. A **forecast line** carries a `channel`, a `store_count`, a `base_velocity_units_per_store_week`, a `promo_weeks` count between 0 and 52, a `promo_lift_pct`, and a `list_price_usd` at four decimals. At most one line per channel per case: a second line on the same `channel` is rejected with `ERR_DUPLICATE_CHANNEL_LINE`. Lines may be added while the case is `DRAFT` or `COMPUTED`; a case that is `LOCKED` or `SUPERSEDED` takes no further lines and answers `ERR_BUSINESS_CASE_INVALID_STATE`. The first line moves the case `DRAFT → COMPUTED`; each subsequent line leaves it in `COMPUTED` (a `COMPUTED → COMPUTED` self-loop) and recomputes every financial field from the **full** line set rather than adjusting incrementally.

**Volume and gross revenue.** Each line is evaluated on its own first. Its raw annual units are the `store_count` multiplied by `base_velocity_units_per_store_week`, multiplied in turn by an effective week count equal to 52 plus the product of `promo_weeks` and `promo_lift_pct` divided by 100. That raw figure is rounded half up to a whole number and stored as `line_units`, and `line_revenue_usd` is `line_units` multiplied by `list_price_usd`, rounded half up to two decimal places. **Both per-line roundings happen before any summation**, which is load-bearing: summing raw units first and rounding once at the end can differ by a unit, and rounding revenue only once can differ by a cent. Independently, `avg_list_price_usd` is the store-count-weighted mean list price — the sum over lines of `list_price_usd` multiplied by `store_count`, divided by the sum of `store_count` across lines, rounded half up to four decimal places.

The two variants then diverge:

- Under `BOTTOM_UP`, `annual_units` is the sum of the stored `line_units` and `gross_revenue_usd` is the sum of the stored `line_revenue_usd`. `category_size_units_year` and `target_share_pct` are ignored entirely.
- Under `TOP_DOWN`, `annual_units` is `category_size_units_year` multiplied by `target_share_pct` divided by 100, rounded half up to a whole number, and `gross_revenue_usd` is that `annual_units` multiplied by `avg_list_price_usd`, rounded half up to two decimal places. Here the lines contribute nothing but the weighted average price.

A case with no lines at all leaves `annual_units` at 0, `gross_revenue_usd` at `0.00` and `avg_list_price_usd` at `0.0000`.

**Financials.** With volume settled, the remaining fields are computed in a pinned nine-step order, each step rounded half up to two decimal places before feeding the next.

1. `trade_spend_rate_pct` is selected from a tiered table keyed on **gross** revenue, not net: `10.00` when `gross_revenue_usd` is below `1000000.00`, `12.00` when it is at least `1000000.00` and below `5000000.00`, and `15.00` when it is at least `5000000.00`. The boundary belongs to the higher tier — gross revenue of exactly `5000000.00` pays 15 percent while `4990000.00` still pays 12.
2. `trade_spend_usd` is `gross_revenue_usd` multiplied by `trade_spend_rate_pct` divided by 100.
3. `net_revenue_usd` is `gross_revenue_usd` less `trade_spend_usd` less `slotting_fees_usd`.
4. `cogs_total_usd` is `annual_units` multiplied by `cogs_per_unit_usd`.
5. `gross_margin_usd` is `net_revenue_usd` less `cogs_total_usd`.
6. `gross_margin_pct` is `gross_margin_usd` divided by `net_revenue_usd`, multiplied by 100 — and it is `0.00` by definition when `net_revenue_usd` is zero. It may be negative when costs exceed net revenue.
7. Three annual cash flows are derived. The year-one flow equals `gross_margin_usd`. The year-two flow is the year-one flow multiplied by 1.15, rounded. The year-three flow is the year-two flow multiplied by 1.08, rounded.
8. `npv_usd` discounts those three flows at a factor equal to 1 plus `discount_rate_pct` divided by 100. The year-one flow is divided by that factor once, the year-two flow by the factor squared, the year-three flow by the factor cubed; **each of the three discounted terms is rounded to two decimals individually**, they are summed, `capex_usd` is subtracted, and the result is rounded again.
9. `payback_months` walks months 1 through 36, adding at each month one twelfth of that month's governing annual flow — the year-one flow for months 1 to 12, the year-two flow for months 13 to 24, the year-three flow for months 25 to 36 — with each monthly instalment rounded to two decimals before being accumulated. `payback_months` is the first month at which the running total reaches or exceeds `capex_usd`. If 36 months never get there, `payback_months` takes the sentinel value 999, meaning never.

Reaching `COMPUTED` is the evidence event for a business-case checklist item: a case whose `case_type` is `PRELIMINARY` auto-approves any `PENDING` `PRELIM_BUSINESS_CASE` item, and a case whose `case_type` is `FINAL` auto-approves any `PENDING` `FINAL_BUSINESS_CASE` item, in both cases with `evidence_url` set to `system://auto-approved`.

**The three hurdles.** A gate's passing branches require the project's authoritative case to clear all three of the gate's bars together: `npv_usd` at or above `npv_hurdle_usd`, `payback_months` at or below `payback_months_max`, and `gross_margin_pct` at or above `gross_margin_floor_pct`. Missing any one on a passing close answers `ERR_BUSINESS_CASE_HURDLE_NOT_MET` (422). How many of the three are cleared also feeds the readiness index, as §3.6 describes.

### 3.5. The Deliverable Checklist

Most checklist items are created for the project automatically when it enters a gate's `stage_from`, but an `InnovationLead` or `GateChair` may add one by hand, supplying the `gate_id` whose checklist it joins, the `deliverable_type`, the accountable `owner_function`, an optional informational `due_at`, and optionally a `prerequisite_deliverable_id`. A live item already occupying the same combination of `project_id`, `gate_id` and `deliverable_type` makes the request a duplicate, rejected with `ERR_DUPLICATE_DELIVERABLE_TYPE`. Each item starts in `PENDING` with `evidence_url`, `submitted_by_user_id` and `decided_by_user_id` all null, `due_at` null unless supplied, `prerequisite_deliverable_id` null unless supplied, and `submission_count` 0.

**Prerequisites form a directed acyclic graph within a project.** An item's `prerequisite_deliverable_id` points at another item that must be settled first, and the edge may be set at creation or afterwards by an `InnovationLead` or `GateChair` pointing the item at a new prerequisite. Either way, if the named prerequisite does not resolve the answer is `ERR_PREREQUISITE_NOT_FOUND` (404), and if the proposed edge would close a loop in the project's existing prerequisite chain the answer is `ERR_DELIVERABLE_CYCLE` (409) — a self-edge is the shortest such loop and is rejected on exactly the same footing as a longer one, so the server walks the whole chain rather than only comparing the two endpoints.

**Submission.** Any of `InnovationLead`, `RnDLead`, `FunctionalReviewer` or `SalesAccountManager` may submit evidence for an item by supplying an `evidence_url`. Submission is admissible from `PENDING` and from `REJECTED`; from anywhere else it answers `ERR_DELIVERABLE_INVALID_STATE`. Two further conditions apply: the item's prerequisite, if any, must itself be `APPROVED` or `WAIVED`, else `ERR_PREREQUISITE_NOT_SATISFIED` (409); and the owning project's `dev_status` must be neither `KILLED` nor `DISCONTINUED`. An accepted submission records `evidence_url` and the acting opaque identifier as `submitted_by_user_id`, and increments `submission_count`. The `PENDING → SUBMITTED` and `REJECTED → SUBMITTED` transitions differ in one respect: a resubmission out of `REJECTED` also clears `decided_by_user_id`, so the item carries no stale decider while it awaits a fresh verdict. `submission_count` counts every entry into `SUBMITTED`, which is how a completed revision loop is evidenced — an item that was rejected once and resubmitted shows `submission_count` 2.

**Decision.** A `FunctionalReviewer` decides a `SUBMITTED` item by supplying a `decision` and an optional `comment`; the item moves `SUBMITTED → APPROVED` or `SUBMITTED → REJECTED` and the acting identifier is recorded as `decided_by_user_id`. Deciding an item in any other state answers `ERR_DELIVERABLE_INVALID_STATE`, and because state outranks segregation of duties, that state error is what a submitter sees if they try to approve their own still-`PENDING` item. Once the item really is `SUBMITTED`, a decider whose identifier equals `submitted_by_user_id` is rejected with `ERR_SELF_APPROVAL_FORBIDDEN`. An approval of one of the four readiness types additionally recomputes the project's `launch_readiness_pct`; approving an evidence type does not.

**Waiver.** A `GateChair` may waive an item with a `reason`, from `PENDING`, `SUBMITTED` or `REJECTED`. The one exception is absolute: a `REGULATORY_CLEARANCE` item can never be waived, and the attempt answers `ERR_REGULATORY_WAIVER_FORBIDDEN` (409). A `WAIVED` item counts as **satisfied** for gate checklist completeness but contributes **nothing** to launch readiness — waiving a manufacturing readiness plan lets a gate close but will never let a launch date lock.

**Completeness.** `deliverable_completeness_pct` on a review measures the gate's own checklist. If the gate's `required_deliverable_types` array is empty the value is `100.00` — an empty checklist is vacuously complete, not zero and not a division error. Otherwise the server counts how many of the required types have an item on that combination of `project_id` and `gate_id` whose `status` is `APPROVED` or `WAIVED`, divides by the number of required types, multiplies by 100 and rounds half up to two decimal places. An item that exists but sits in `PENDING`, `SUBMITTED` or `REJECTED` counts as unsatisfied.

**Evidence-driven auto-approval.** Six of the ten types are never submitted by hand at all. `CONSUMER_CONCEPT_TEST` auto-approves when a concept test is recorded (§3.3). `PRELIM_BUSINESS_CASE` auto-approves when a `PRELIMINARY` case reaches `COMPUTED`, and `FINAL_BUSINESS_CASE` when a `FINAL` case reaches `COMPUTED` (§3.4). `PILOT_SCALE_UP_REPORT` auto-approves when a pilot run completes at or above the yield floor, and `SHELF_LIFE_REPORT` when a stability study closes `PASSED` (§3.7). `REGULATORY_CLEARANCE` auto-approves when a label reaches `APPROVED` or `CONDITIONAL` (§3.7). Every auto-approval takes the `PENDING → APPROVED` path with `evidence_url` set to `system://auto-approved` and leaves `submitted_by_user_id` and `decided_by_user_id` null.

### 3.6. Gate Reviews: Convening, Balloting and the Four-Way Decision

A `GateChair` schedules a review against a gate configuration by supplying the `gate_id` and an informational `scheduled_at`; the review is created in `SCHEDULED` with `decision`, `chair_user_id`, `conditions`, `conditions_due_at` and `closed_at` all null, `vote_count` 0, and `deliverable_completeness_pct` and `readiness_index` both `0.00`. There is no temporal precondition on `scheduled_at`; it documents intent.

**Opening the session** moves the review `SCHEDULED → IN_SESSION` and is where the sequencing rules bite. The project's `dev_status` must equal the gate's `stage_from`, else `ERR_PROJECT_INVALID_STATE`. The gate's `gate_number` must equal the project's `next_gate_number`, else `ERR_GATE_SEQUENCE_VIOLATION` (409) — this is what stops a project skipping a gate, and what forces a recycled project to re-run the earlier gate. No other review of the same project may already be `IN_SESSION`, else `ERR_GATE_REVIEW_ALREADY_IN_SESSION` (409). And `open_gate_conditions` on the project must be false, else `ERR_GATE_CONDITIONS_OPEN` (409) — unresolved conditions from an earlier conditional pass block the next gate entirely. Those three business-safety checks are evaluated in exactly that order. Opening computes and stores `deliverable_completeness_pct` and `readiness_index`; note carefully that **checklist completeness is not required to open** a review, only to close one on a passing branch.

**The readiness index** is a composite of four sub-scores, each on a 0-to-100 scale. The first is the review's own `deliverable_completeness_pct`. The second is the `concept_score` of the project's authoritative concept test, or `0.00` when the project has none. The third is a hurdle sub-score: `100.00` when the authoritative business case clears all three of `npv_hurdle_usd`, `payback_months_max` and `gross_margin_floor_pct` together, `50.00` when it clears exactly two of the three, and `0.00` otherwise — including when no business case exists at all. The fourth is a yield sub-score: the `best_pilot_yield_pct` of the project's current formulation, capped at `100.00`, or `0.00` when the project has no non-superseded formulation. Those four — completeness, concept, hurdle, yield, in that order — are combined under a weight vector chosen by the project's `project_type`: `NEW_BRAND` weights them 0.35, 0.30, 0.20 and 0.15; `LINE_EXTENSION` weights them 0.30, 0.25, 0.25 and 0.20; `RENOVATION` weights them 0.40, 0.20, 0.20 and 0.20. The weighted sum is then multiplied by a category adjustment factor — `1.00` for `BEVERAGE`, `1.00` for `SNACK`, `0.95` for `DAIRY`, `1.05` for `HOUSEHOLD` — and the product is rounded half up to two decimal places **once, after the category factor is applied**, then capped at `100.00`. The same project profile therefore scores lower in dairy and higher in household than in beverage or snack.

**Balloting.** A `FunctionalReviewer` or `RegulatoryApprover` casts one ballot per cross-functional seat, supplying the `function`, the `vote` and an optional `rationale`; the ballot is stored against the review's `gate_review_id` with the acting identifier as `voter_user_id`, and the review's `vote_count` increments. A review must be `IN_SESSION` to take ballots, else `ERR_GATE_REVIEW_INVALID_STATE`. Only one ballot per `function` per review is permitted: a second ballot naming a seat that already voted is rejected with `ERR_DUPLICATE_FUNCTION_VOTE` (409). And the project's owner may not vote at all — a `voter_user_id` equal to the project's `owner_user_id` is rejected with `ERR_OWNER_CANNOT_VOTE` (403).

**Closing** is the branching heart of the system. A `GateChair` closes an `IN_SESSION` review, optionally supplying `conditions` and `conditions_due_at`. The chair's identifier must not appear as the `voter_user_id` of any ballot on this review, else `ERR_CHAIR_CANNOT_VOTE_AND_CLOSE` (403). `vote_count` must be at least the gate's `quorum_size`, else `ERR_QUORUM_NOT_MET` (409) — and because quorum is checked **before the decision is derived**, a lone `REJECT` ballot under quorum reports the quorum error rather than killing the project. With quorum met, the ballot set determines which of four branches runs:

- **`IN_SESSION → PASSED`** when no ballot is `REJECT` and none is `APPROVE_WITH_CONDITIONS`. The review's `decision` becomes `PASSED`, `closed_at` takes the current instant, `chair_user_id` takes the acting identifier, and `deliverable_completeness_pct` and `readiness_index` are recomputed and re-frozen at their closing values. The project's `dev_status` advances to the gate's `stage_to`, and the authoritative business case moves `COMPUTED → LOCKED`, becoming the plan basis all post-launch tracking is measured against.
- **`IN_SESSION → CONDITIONAL_PASS`** when no ballot is `REJECT` but at least one is `APPROVE_WITH_CONDITIONS`. This branch additionally requires `conditions` to be a non-empty string and `conditions_due_at` to be strictly after the current instant; omitting either is a shape violation answering `ERR_INVALID_REQUEST`. `decision` becomes `CONDITIONAL_PASS`, the project's `open_gate_conditions` is set to true, `closed_at` and `chair_user_id` are stamped, the two frozen figures are re-frozen, the project's `dev_status` advances to the gate's `stage_to` exactly as on the passing branch, and the authoritative business case likewise moves `COMPUTED → LOCKED`. The project moves forward but cannot convene its next gate until the conditions are settled.
- **`IN_SESSION → RECYCLED`** when at least one ballot is `REJECT` and no rejecting ballot came from a seat listed in the gate's `veto_functions`. `decision` becomes `RECYCLED`, `closed_at` and `chair_user_id` are stamped, and the project steps **back** one stage.
- **`IN_SESSION → KILLED`** when at least one `REJECT` ballot came from a seat listed in `veto_functions`. `decision` becomes `KILLED` and the full kill cascade runs.

Both passing branches — and only the passing branches — must clear three further bars, evaluated in this order: `deliverable_completeness_pct` must be exactly `100.00`, else `ERR_DELIVERABLE_CHECKLIST_INCOMPLETE` (422); `readiness_index` must be at least the gate's `readiness_floor_index`, else `ERR_GATE_READINESS_BELOW_FLOOR` (422); and the authoritative business case must clear all three financial hurdles, else `ERR_BUSINESS_CASE_HURDLE_NOT_MET` (422). A `RECYCLED` or `KILLED` close is deliberately permitted against an incomplete checklist and a low readiness index — the point of those branches is to stop a project that is not ready.

**What advancing means.** A passing close of a gate whose `stage_from` is `SCREENED` and whose `stage_to` is `PILOT_QUALIFIED` moves `dev_status` `SCREENED → PILOT_QUALIFIED`, sets `next_gate_number` to the gate's `gate_number` plus one, and then auto-creates the checklist of the stage gate registered for the project's `category` at that new `next_gate_number` — but only when such a configuration exists **and** its `stage_from` equals the project's new `dev_status`, and again skipping any combination of `gate_id` and `deliverable_type` that already exists. A passing close of a gate whose `stage_from` is `PILOT_QUALIFIED` and whose `stage_to` is `LAUNCH_READY` moves `dev_status` `PILOT_QUALIFIED → LAUNCH_READY`, sets `next_gate_number` to the gate's `gate_number` plus one, and recomputes `launch_readiness_pct`. On either passing gate, a `CONDITIONAL_PASS` decision additionally sets `open_gate_conditions` to true.

**What stepping back means.** A recycle moves the project one rung down the development ladder `IDEA`, `SCREENED`, `PILOT_QUALIFIED`, `LAUNCH_READY` — specifically to the rung immediately below the gate's `stage_from` — with `SCREENED` as the floor, and increments `recycle_count`. Recycling a gate whose `stage_from` is `PILOT_QUALIFIED` therefore drives `dev_status` `PILOT_QUALIFIED → SCREENED` and sets `next_gate_number` to the greater of 2 and the gate's `gate_number` minus one; the gate-2 checklist is re-created for any combination of `gate_id` and `deliverable_type` that no longer exists on the project. Recycling a gate whose `stage_from` is `SCREENED` would step below the floor, so `dev_status` self-loops `SCREENED → SCREENED`, `next_gate_number` stays 2, and `recycle_count` still increments.

**The kill cascade.** A `KILLED` decision drives `dev_status` to `KILLED` from either `SCREENED` or `PILOT_QUALIFIED`, and the same cascade runs in both cases. Every checklist item on the project whose `status` is `PENDING`, `SUBMITTED` or `REJECTED` moves to `CANCELLED`. Every other gate review of the project still in `SCHEDULED` moves to `CANCELLED`. Every trade presentation of the project whose `status` is `PLANNED`, `PRESENTED`, `DEFERRED` or `ACCEPTED` moves to `WITHDRAWN`, each one decrementing its reset window's `booked_slot_count`, and each one that was `ACCEPTED` also reducing the project's `authorized_acv_pct` by that retailer's `acv_contribution_pct`. Finally the commercial track is reset: `commercial_status` returns to `NOT_STARTED`, and `launch_date` and `shelf_reset_window_id` are cleared to null.

**Settling conditions.** A `GateChair` clears the conditions of a `CONDITIONAL_PASS` review by supplying a `resolution_note`. The current instant must not have passed `conditions_due_at` — the deadline instant itself still counts as on time — else `ERR_CONDITIONS_DUE_PASSED` (409); and the gate checklist's `deliverable_completeness_pct` must be `100.00` at clearing time, else `ERR_DELIVERABLE_CHECKLIST_INCOMPLETE` (422). Clearing takes the review `CONDITIONAL_PASS → PASSED`, rewrites `decision` to `PASSED`, and sets the project's `open_gate_conditions` back to false, unblocking the next gate. If instead the deadline lapses, a `PortfolioAdmin` expires the conditions: the current instant must have passed `conditions_due_at`, else `ERR_CONDITIONS_NOT_DUE` (409). Expiry takes the review `CONDITIONAL_PASS → RECYCLED`, sets `open_gate_conditions` to false, steps the project back one stage by the same ladder-and-floor rule as a recycled close, and increments `recycle_count`.

### 3.7. Formulation, Pilot Scale-Up, Stability Testing and Label Clearance

An `RnDLead` creates a formulation revision under the project, declaring `expected_project_version` per §2.6 and supplying a `spec_summary` covering formula, packaging and process, the `allergen_regime` the product requires, a `target_shelf_life_days` of at least 1 day, and an estimated `unit_cost_usd` at four decimals. `revision` is assigned by the server as a 1-based ordinal within the project, so the first revision is 1. A new revision starts in `DRAFT` with `best_pilot_yield_pct` `0.00`.

**Booking pilot plant time.** Against a formulation, the same `RnDLead` books a run on a named `pilot_line_id` for a `window_start` and a `window_end` strictly after it, declaring `planned_units` of at least 1 and a `committed_cost_usd`. The formulation must not be `SUPERSEDED`, else `ERR_FORMULATION_INVALID_STATE`. Two guards then apply, in this order.

First, **line exclusivity with an allergen-aware changeover buffer**. Each run derives `effective_buffer_minutes` from the line's base `changeover_buffer_minutes`: unchanged when the formulation's `allergen_regime` equals the line's `allergen_regime`, and **doubled** when the two differ, because switching a line between, say, a `NUT` regime and a `NONE` regime costs a full sanitation changeover. Booking then compares the requested interval — half-open, running from `window_start` up to but not including `window_end` extended by `effective_buffer_minutes` — pairwise against the same buffer-extended interval of every `SCHEDULED` or `RUNNING` run already on that line, whatever project it belongs to. Any overlap is rejected with `ERR_PILOT_LINE_CONFLICT` (409); a run starting exactly at the instant a previous run's buffer expires is not an overlap and is accepted.

Second, the **budget cap** of §2.10: if adding this run's `committed_cost_usd` to the project's live commitments would exceed `development_budget_cap_usd`, the booking answers `ERR_DEV_BUDGET_EXCEEDED` (422). Because the budget band is the last one evaluated, a booking that both conflicts on the line and overruns the cap reports the line conflict.

**Running and completing.** A run starts in `SCHEDULED` and moves `SCHEDULED → RUNNING` when the `RnDLead` starts it; the run must actually be `SCHEDULED`, else `ERR_PILOT_RUN_INVALID_STATE` (409), the current instant must have reached `window_start`, else `ERR_PILOT_RUN_NOT_DUE` (409), and the parent formulation must still not be `SUPERSEDED`. Completing a run requires it to be `RUNNING` and cancelling one requires it to be `SCHEDULED` or `RUNNING`; from any other status both answer `ERR_PILOT_RUN_INVALID_STATE`. Completing a `RUNNING` run takes `actual_units` (which must be at least 0) and moves it `RUNNING → COMPLETED`, computing `yield_pct` as `actual_units` divided by `planned_units`, multiplied by 100, rounded half up to two decimal places. The pilot yield floor is `85.00` percent. A yield at or above the floor drives the formulation to `PILOT_PASSED` — from `DRAFT → PILOT_PASSED` on a first success, or `PILOT_FAILED → PILOT_PASSED` when a later run redeems an earlier failure — and auto-approves the `PILOT_SCALE_UP_REPORT` checklist item. A yield below the floor drives the formulation `DRAFT → PILOT_FAILED` and approves nothing. Either way `best_pilot_yield_pct` is updated to the highest `yield_pct` across the formulation's `COMPLETED` runs, which is the figure the readiness index reads.

A run in `SCHEDULED` or `RUNNING` may be cancelled with a `reason`, moving it to `CANCELLED`. Cancellation releases its `committed_cost_usd` from the project's ledger — the field returns to exactly its pre-booking value — and frees the line window, so the same slot and the same cost can be booked again.

**Stability testing.** A `PILOT_PASSED` formulation goes into stability testing. The `RnDLead` opens a study declaring `expected_formulation_version` per §2.6, a planned `duration_days` of at least 1, a `committed_cost_usd` and a `start_at` instant. The study starts `ACTIVE` with an empty `timepoints` list, `min_quality_score` null and `verdict` null, and its `committed_cost_usd` joins the project's live commitments immediately — so the same `ERR_DEV_BUDGET_EXCEEDED` cap applies here as to pilot runs.

Observations are appended one at a time as a `day_index` and a `quality_score`. Each `day_index` must be strictly greater than every `day_index` already recorded on the study, else `ERR_TIMEPOINT_OUT_OF_ORDER` (409); the stored `timepoints` list is therefore kept sorted by `day_index` ascending by construction. Appending to a closed study answers `ERR_STUDY_INVALID_STATE`. Each append refreshes `min_quality_score` to the lowest `quality_score` recorded so far.

The verdict logic has two triggers. Any recorded `quality_score` below the absolute floor of `60.00` closes the study `ACTIVE → FAILED` **immediately**, with `verdict` `FAIL`, without waiting for the planned duration — a quality collapse at day 90 does not need to wait for day 180. Otherwise the study closes when an observation arrives whose `day_index` is at least `duration_days`. At that moment the server picks the **target point**: the recorded timepoint with the largest `day_index` that does not exceed the formulation's `target_shelf_life_days`. The `verdict` is `PASS` when a target point exists, its `quality_score` is at least the target floor of `70.00`, and `min_quality_score` across the whole series is at least `60.00`; otherwise the `verdict` is `FAIL`. A target point sitting exactly at `70.00` passes; one cent below fails. A `PASS` closes the study `ACTIVE → PASSED`, drives the formulation `PILOT_PASSED → SHELF_LIFE_CLEARED` and auto-approves the `SHELF_LIFE_REPORT` checklist item. A `FAIL` closes the study `ACTIVE → FAILED` and leaves the formulation at whatever status it already held. Note that both `PASSED` and `FAILED` studies remain in the ledger basis — only abandonment releases a study's commitment.

**Drafting pack artwork and claims.** An `InnovationLead` drafts pack artwork by naming the `formulation_id` it describes, a `label_version` string and a `claims` array of between 1 and 10 non-empty strings. The named formulation must belong to the project the draft is created under, else `ERR_FORMULATION_PROJECT_MISMATCH` (409). A new draft starts in `DRAFT` with an empty `unsupported_claims` array and `decided_by_user_id` null.

Sending artwork to review moves it `DRAFT → IN_REVIEW`, and resubmitting after a rejection moves it `REJECTED → IN_REVIEW`; the two differ in that a resubmission out of `REJECTED` also clears `unsupported_claims`, so the regulatory reviewer starts from a clean flag list. Submission from any other status answers `ERR_LABEL_INVALID_STATE`. Critically, the described formulation must be `SHELF_LIFE_CLEARED` at submission time — claims cannot be reviewed against a formula whose stability is unproven — and a formulation in any other status answers `ERR_FORMULATION_INVALID_STATE` (409).

A `RegulatoryApprover` then records a `decision` on an `IN_REVIEW` label, optionally with a `comment`, along three branches. `APPROVE` moves it `IN_REVIEW → APPROVED`. `APPROVE_WITH_CHANGES` moves it `IN_REVIEW → CONDITIONAL` and requires a non-empty `unsupported_claims` array naming the claims that were not substantiated — an empty or absent list answers `ERR_UNSUPPORTED_CLAIMS_REQUIRED` (422). `REJECT` moves it `IN_REVIEW → REJECTED`. Both clearing branches — `APPROVED` and `CONDITIONAL` — auto-approve the project's `REGULATORY_CLEARANCE` checklist item with equal effect; the rejecting branch approves nothing. The acting identifier is recorded as `decided_by_user_id` on all three branches.

**The depth-four supersede cascade.** Creating the next formulation revision supersedes the previous one, and the consequences run four levels deep in one accepted write. The previous revision moves to `SUPERSEDED` — from `DRAFT → SUPERSEDED` or from `SHELF_LIFE_CLEARED → SUPERSEDED` alike. Level one: its pilot runs in `SCHEDULED` or `RUNNING` move to `CANCELLED`, releasing their `committed_cost_usd`, and its studies still `ACTIVE` move `ACTIVE → ABANDONED`, likewise releasing theirs. Level two: any label approval describing the superseded revision whose `status` is `APPROVED` or `CONDITIONAL` moves to `INVALIDATED` — both statuses take that path identically. Level three: because the label that cleared it is gone, the project's `REGULATORY_CLEARANCE` checklist item moves `APPROVED → PENDING` with `evidence_url` cleared, which is why `APPROVED` is not a terminal checklist status. Level four: if the project's `commercial_status` was `LAUNCH_LOCKED` and the superseded revision carried that `APPROVED` or `CONDITIONAL` label, the launch lock slips — `commercial_status` moves `LAUNCH_LOCKED → LOCK_SLIPPED`, `launch_date` and `shelf_reset_window_id` are cleared to null, and `launch_readiness_pct` is recomputed.

### 3.8. Customer Sell-In and Retailer Reset Windows

A `SalesAccountManager` books a trade presentation for the project by naming the `retailer_id` receiving it, the `shelf_reset_window_id` it targets, the `scheduled_at` instant, and the `proposed_sku_count` of at least 1 SKU. `accepted_sku_count` is null until the retailer answers. The presentation starts in `PLANNED` and the project's `commercial_status` moves to `SELL_IN_SCHEDULED` — from `NOT_STARTED → SELL_IN_SCHEDULED` on a first booking, and equally from `SELL_IN_REJECTED → SELL_IN_SCHEDULED` when the team returns to a retailer after an earlier refusal. From `NOT_STARTED`, booking additionally requires `dev_status` in `PILOT_QUALIFIED`, `LAUNCH_READY`, `LAUNCHED` or `IN_MARKET_FIX`; from `SELL_IN_REJECTED`, it requires only that `dev_status` be neither `KILLED` nor `DISCONTINUED`. Either way the window's `booked_slot_count` increments.

Booking is guarded by four rules on top of the state check. The window's aggregate capacity comes first: if `booked_slot_count` has already reached the window's `max_presentations`, the booking answers `ERR_RESET_WINDOW_CAPACITY_FULL` (409) — each individual presentation is perfectly legal, but the collective count over the window interval is capped. Then the three referential rules of §2.11 apply: the window must belong to the named retailer (`ERR_WINDOW_RETAILER_MISMATCH`), the window's `category` must equal the project's `category` (`ERR_WINDOW_CATEGORY_MISMATCH`), and the retailer's `channel` must appear as the `channel` of a forecast line on the project's authoritative business case (`ERR_CHANNEL_NOT_FORECAST`) — binding the sell-in plan back to the volume the business case promised. Finally the trade-presentation timing rule: `scheduled_at` must precede the window's `window_start` by at least the retailer's `presentation_lead_days` whole days, else `ERR_PRESENTATION_LEAD_TIME_VIOLATION` (409). A gap exactly equal to the lead time is accepted; anything closer is not.

**Running the presentation.** A `PLANNED` presentation is marked as presented once the current instant has reached its `scheduled_at`; earlier attempts answer `ERR_PRESENTATION_NOT_DUE` (409). The presentation moves `PLANNED → PRESENTED` and the project's `commercial_status` moves `SELL_IN_SCHEDULED → PRESENTED`.

**Recording the retailer's answer.** From `PRESENTED`, the account manager records an `outcome` along three branches, optionally with `accepted_sku_count`:

- `ACCEPTED` requires `accepted_sku_count` to be present and to not exceed `proposed_sku_count`; one more than proposed answers `ERR_ACCEPTED_SKU_EXCEEDS_PROPOSED` (422) while equality is accepted. The presentation moves `PRESENTED → ACCEPTED`, the project's `authorized_acv_pct` increases by the retailer's `acv_contribution_pct` capped at `100.00`, and `commercial_status` moves `PRESENTED → AUTHORIZED`. `authorized_acv_pct` is thus the capped sum of `acv_contribution_pct` over the project's `ACCEPTED` presentations.
- `DEFERRED` moves the presentation `PRESENTED → DEFERRED` and the project's `commercial_status` back to `SELL_IN_SCHEDULED`. The window slot stays booked, because a deferred conversation still occupies the retailer's reset slot — `booked_slot_count` is deliberately left unchanged.
- `REJECTED` moves the presentation `PRESENTED → REJECTED` and decrements the window's `booked_slot_count`. The project's `commercial_status` moves `PRESENTED → SELL_IN_REJECTED` only when no other presentation of this project is still in `PLANNED`, `PRESENTED`, `DEFERRED` or `ACCEPTED`; while any live presentation remains, the commercial track keeps whatever state that other conversation put it in.

**Withdrawal.** A presentation in `PLANNED`, `PRESENTED`, `DEFERRED` or `ACCEPTED` may be withdrawn with a `reason`, moving it to `WITHDRAWN` and decrementing the window's `booked_slot_count`. Withdrawing a presentation that was `ACCEPTED` additionally reduces the project's `authorized_acv_pct` by that retailer's `acv_contribution_pct`, and is barred once the project's `commercial_status` is `SHIPPED` — you cannot un-authorise a distribution point after the product has shipped, and the attempt answers `ERR_PRESENTATION_INVALID_STATE`.

### 3.9. Launch Readiness, the Date Lock, and Launch

**Launch readiness** is a weighted measure over the four readiness checklist types, renormalised over only those the project's commercialisation gate actually demands. The type weights are `MANUFACTURING_READINESS` 0.35, `DISTRIBUTION_READINESS` 0.25, `MARKETING_LAUNCH_PLAN` 0.20 and `SALES_SELL_IN_PLAN` 0.20. The required set is the intersection of those four types with the `required_deliverable_types` of the stage gate whose `stage_to` is `LAUNCH_READY`. The denominator is the sum of the weights over that required set; the numerator is the sum of the weights over those required types whose checklist item is `APPROVED`, and a `WAIVED` item contributes nothing to the numerator even though it satisfies gate completeness. `launch_readiness_pct` is `0.00` when the denominator is zero, and otherwise the numerator divided by the denominator, multiplied by 100, rounded half up to two decimal places. Renormalisation matters: a gate demanding all four types shows `35.00` when only manufacturing is approved, whereas a gate demanding only manufacturing and sales shows `63.64` for the same single approval, and reaches `100.00` — the value that unlocks the date lock — with just those two approved. The figure is recomputed whenever a readiness item is approved or waived, whenever a gate closes a project into `LAUNCH_READY`, and whenever the label-invalidation cascade runs.

A dedicated launch-readiness read exposes the live picture without storing anything new: the current `launch_readiness_pct`, a `blocking_deliverable_types` array listing the required readiness types not yet `APPROVED` in checklist order, the current `authorized_acv_pct`, the locked `launch_date` if any, and an `earliest_lockable_date` computed on every read as the current instant plus the 45-whole-day lock lead time. `earliest_lockable_date` is derived on demand and never persisted.

**Locking the date.** A `GateChair` locks the launch by supplying a `launch_date` and the `shelf_reset_window_id` it must fall inside. The project must hold `dev_status` `LAUNCH_READY` with `commercial_status` either `AUTHORIZED` or `LOCK_SLIPPED` — the first lock and a re-lock after a slip follow identical rules, taking `AUTHORIZED → LAUNCH_LOCKED` or `LOCK_SLIPPED → LAUNCH_LOCKED` respectively. Five substantive conditions then apply, in band order. The window's `category` must equal the project's `category`, else `ERR_WINDOW_CATEGORY_MISMATCH` (409). An `APPROVED` or `CONDITIONAL` label approval must exist on the project's current formulation, else `ERR_LABEL_NOT_APPROVED` (409) — regulatory, claims and label clearance genuinely gates commercialisation. The `launch_date` must fall inside the closed interval from the window's `window_start` to its `window_end`, both endpoints inclusive, else `ERR_LAUNCH_DATE_OUTSIDE_WINDOW` (409). The `launch_date` must be at least 45 whole days after the current instant, else `ERR_LOCK_LEAD_TIME_VIOLATION` (409); because containment is checked first, a date both outside the window and too soon reports the containment error. And `launch_readiness_pct` must be exactly `100.00`, else `ERR_LAUNCH_READINESS_INCOMPLETE` (422) — manufacturing, distribution, marketing and sales must all be approved before a date can be committed to a retailer. A successful lock stores `launch_date` and `shelf_reset_window_id` on the project and moves `commercial_status` to `LAUNCH_LOCKED`.

**Executing the launch.** A `GateChair` launches the project once the current instant has reached the locked `launch_date`; pulling the date forward answers `ERR_LAUNCH_DATE_NOT_REACHED` (409). Launch requires `dev_status` `LAUNCH_READY`, `commercial_status` `LAUNCH_LOCKED` and `launch_readiness_pct` still exactly `100.00`, and it is the one request that moves both tracks at once: `dev_status` goes `LAUNCH_READY → LAUNCHED` and `commercial_status` goes `LAUNCH_LOCKED → SHIPPED` in the same write. `SHIPPED` is terminal on the commercial track.

**Post-launch tracking.** A `PortfolioAdmin` reports each quarter with a `period_index`, the `actual_units` sold, the `actual_net_revenue_usd` realised, the `actual_gross_margin_usd` realised (which may be negative), and the `attainment_basis` to judge by. Reporting requires `dev_status` `LAUNCHED` or `IN_MARKET_FIX`. Two gates precede the arithmetic: the project's authoritative business case must be in `status` `LOCKED`, else `ERR_NO_LOCKED_BUSINESS_CASE` (409) — which bites both when no gate ever locked a case and when a newer case was raised after the lock, displacing the locked one as authoritative; and `period_index` must be exactly the project's existing period count plus one, else `ERR_PERIOD_SEQUENCE_VIOLATION` (409), so periods arrive in order with no gaps and no repeats.

The plan basis is `plan_units_per_period`, the locked case's `annual_units` divided by the four periods in a year, rounded half up to two decimal places. Both attainment figures are then computed and **both are always stored**, whichever basis was reported. `attainment_cumulative_pct` is the sum of `actual_units` over periods 1 through `period_index` divided by `plan_units_per_period` multiplied by `period_index`, that quotient multiplied by 100 and rounded half up to two decimal places. `attainment_trailing_pct` is this period's `actual_units` alone divided by `plan_units_per_period`, multiplied by 100 and rounded half up to two decimal places. `attainment_pct` is then set to `attainment_cumulative_pct` when `attainment_basis` is `CUMULATIVE` and to `attainment_trailing_pct` when it is `TRAILING`. The cumulative basis averages every period to date, so a weak quarter is cushioned by earlier strength; the trailing basis reacts immediately to the period just reported and can therefore reach a harsher verdict than the cumulative basis on identical inputs. At period 1 the two coincide by construction.

The `decision` follows from `attainment_pct` against two floors: `CONTINUE` when it is at least `90.00`, `FIX` when it is at least `70.00` but below `90.00`, and `DISCONTINUE` when it is below `70.00`. The project's `post_launch_decision` mirrors the decision of its highest-`period_index` period, and `dev_status` follows:

- A `FIX` decision moves `dev_status` `LAUNCHED → IN_MARKET_FIX`; a project already in `IN_MARKET_FIX` stays there.
- A `CONTINUE` decision moves `dev_status` `IN_MARKET_FIX → LAUNCHED`; a project already `LAUNCHED` stays there.
- A `DISCONTINUE` decision moves `dev_status` to `DISCONTINUED` from either `LAUNCHED` or `IN_MARKET_FIX`, and in both cases runs the same wind-down cascade: every trade presentation of the project whose `status` is `PLANNED`, `PRESENTED` or `DEFERRED` moves to `WITHDRAWN`, each decrementing its window's `booked_slot_count`. Note the deliberate contrast with the kill cascade of §3.6: discontinuation leaves `ACCEPTED` presentations alone, because the retailer authorisation already earned is a matter of record once the product shipped, whereas a vetoed kill withdraws them too and unwinds their ACV.

`DISCONTINUED` and `KILLED` are the two terminal development states; a project in either accepts no further checklist submissions and no further development or commercial work.

## 4. Endpoint Definitions

Operations that create a new stored row return `201 Created`. Operations that mutate an existing row — every state transition, every waiver, every decision, the clock setter, and the launch date lock — return `200 OK`, as do all reads. Every write endpoint returns the affected primary resource in `data`; the launch-readiness read returns a computed object rather than a stored row. All seven roles may call every `GET` endpoint, shown below as "All roles".

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock used by every temporal rule | PortfolioAdmin |
| POST | `/stage-gates` | Register a gate configuration for one category | PortfolioAdmin |
| GET | `/stage-gates` | List gate configurations, newest first | All roles |
| GET | `/stage-gates/{gate_id}` | Read one gate configuration | All roles |
| POST | `/retailers` | Register a retail customer | PortfolioAdmin |
| GET | `/retailers` | List retailers | All roles |
| GET | `/retailers/{retailer_id}` | Read one retailer | All roles |
| POST | `/retailers/{id}/shelf-reset-windows` | Open a category shelf reset window with slot capacity | PortfolioAdmin |
| GET | `/retailers/{id}/shelf-reset-windows` | List a retailer's reset windows | All roles |
| GET | `/shelf-reset-windows/{shelf_reset_window_id}` | Read one reset window with its live slot count | All roles |
| POST | `/pilot-lines` | Register a pilot plant line | PortfolioAdmin |
| GET | `/pilot-lines` | List pilot lines | All roles |
| GET | `/pilot-lines/{pilot_line_id}` | Read one pilot line | All roles |
| POST | `/innovation-projects` | Intake a new idea | InnovationLead |
| GET | `/innovation-projects` | List projects | All roles |
| GET | `/innovation-projects/{project_id}` | Read one project with both status tracks and all derived fields | All roles |
| GET | `/innovation-projects/{id}/launch-readiness` | Computed read: readiness, blocking types, ACV and earliest lockable date | All roles |
| POST | `/innovation-projects/{id}/screen` | Gate 1 idea screening | GateChair |
| POST | `/innovation-projects/{id}/concept-tests` | Record a consumer concept test | InnovationLead |
| GET | `/innovation-projects/{id}/concept-tests` | List a project's concept tests | All roles |
| POST | `/innovation-projects/{id}/business-cases` | Open a business case (optimistic concurrency on the project) | InnovationLead |
| GET | `/innovation-projects/{id}/business-cases` | List a project's business cases | All roles |
| GET | `/business-cases/{business_case_id}` | Read one business case with all financial outputs | All roles |
| POST | `/business-cases/{id}/forecast-lines` | Add a channel forecast line and recompute the case | InnovationLead |
| GET | `/business-cases/{id}/forecast-lines` | List a case's forecast lines | All roles |
| POST | `/innovation-projects/{id}/deliverables` | Add a checklist item beyond the auto-created set | InnovationLead, GateChair |
| GET | `/deliverables` | List checklist items | All roles |
| GET | `/deliverables/{deliverable_id}` | Read one checklist item | All roles |
| POST | `/deliverables/{id}/submit` | Submit evidence for a checklist item | InnovationLead, RnDLead, FunctionalReviewer, SalesAccountManager |
| POST | `/deliverables/{id}/decide` | Approve or reject a submitted checklist item | FunctionalReviewer |
| POST | `/deliverables/{id}/waive` | Waive a checklist item | GateChair |
| POST | `/deliverables/{id}/set-prerequisite` | Point a checklist item at a prerequisite item | InnovationLead, GateChair |
| POST | `/innovation-projects/{id}/gate-reviews` | Schedule a gate review against a gate configuration | GateChair |
| GET | `/gate-reviews` | List gate reviews | All roles |
| GET | `/gate-reviews/{gate_review_id}` | Read one gate review with its frozen figures | All roles |
| POST | `/gate-reviews/{id}/open` | Open the session and compute completeness and readiness | GateChair |
| POST | `/gate-reviews/{id}/votes` | Cast one cross-functional ballot | FunctionalReviewer, RegulatoryApprover |
| GET | `/gate-reviews/{id}/votes` | List the ballots of one review | All roles |
| POST | `/gate-reviews/{id}/close` | Derive the go/no-go decision and apply the branch cascade | GateChair |
| POST | `/gate-reviews/{id}/clear-conditions` | Clear a conditional pass, promoting it to passed | GateChair |
| POST | `/gate-reviews/{id}/expire-conditions` | Expire overdue conditions, recycling the project | PortfolioAdmin |
| POST | `/innovation-projects/{id}/formulations` | Create the next formulation revision (optimistic concurrency on the project) | RnDLead |
| GET | `/innovation-projects/{id}/formulations` | List a project's formulation revisions | All roles |
| GET | `/formulations/{formulation_id}` | Read one formulation revision | All roles |
| POST | `/formulations/{id}/pilot-runs` | Book a pilot plant window | RnDLead |
| GET | `/pilot-runs` | List pilot runs | All roles |
| GET | `/pilot-runs/{pilot_run_id}` | Read one pilot run | All roles |
| POST | `/pilot-runs/{id}/start` | Start a booked run once its window has opened | RnDLead |
| POST | `/pilot-runs/{id}/complete` | Complete a run and compute its yield | RnDLead |
| POST | `/pilot-runs/{id}/cancel` | Cancel a booked or running run and release its cost | RnDLead |
| POST | `/formulations/{id}/shelf-life-studies` | Open a stability study (optimistic concurrency on the formulation) | RnDLead |
| GET | `/formulations/{id}/shelf-life-studies` | List a formulation's stability studies | All roles |
| GET | `/shelf-life-studies/{shelf_life_study_id}` | Read one study with its timepoint series | All roles |
| POST | `/shelf-life-studies/{id}/timepoints` | Append a stability observation | RnDLead |
| POST | `/innovation-projects/{id}/label-approvals` | Draft pack artwork and claims against one formulation | InnovationLead |
| GET | `/label-approvals` | List label approvals | All roles |
| GET | `/label-approvals/{label_approval_id}` | Read one label approval | All roles |
| POST | `/label-approvals/{id}/submit` | Send artwork to regulatory review | InnovationLead |
| POST | `/label-approvals/{id}/decide` | Record the regulatory decision | RegulatoryApprover |
| POST | `/innovation-projects/{id}/sell-in-presentations` | Book a trade presentation into a reset window | SalesAccountManager |
| GET | `/sell-in-presentations` | List trade presentations | All roles |
| GET | `/sell-in-presentations/{presentation_id}` | Read one trade presentation | All roles |
| POST | `/sell-in-presentations/{id}/present` | Record that the presentation happened | SalesAccountManager |
| POST | `/sell-in-presentations/{id}/record-outcome` | Record the retailer's answer | SalesAccountManager |
| POST | `/sell-in-presentations/{id}/withdraw` | Withdraw a live presentation | SalesAccountManager |
| POST | `/innovation-projects/{id}/launch-lock` | Lock the launch date inside a reset window | GateChair |
| POST | `/innovation-projects/{id}/launch` | Execute the launch, moving both status tracks | GateChair |
| POST | `/innovation-projects/{id}/post-launch-periods` | Report a post-launch quarter and record the decision | PortfolioAdmin |
| GET | `/innovation-projects/{id}/post-launch-periods` | List a project's reported periods | All roles |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_PROJECT_NOT_FOUND` | 404 |
| `ERR_STAGE_GATE_NOT_FOUND` | 404 |
| `ERR_GATE_REVIEW_NOT_FOUND` | 404 |
| `ERR_DELIVERABLE_NOT_FOUND` | 404 |
| `ERR_PREREQUISITE_NOT_FOUND` | 404 |
| `ERR_BUSINESS_CASE_NOT_FOUND` | 404 |
| `ERR_FORMULATION_NOT_FOUND` | 404 |
| `ERR_PILOT_LINE_NOT_FOUND` | 404 |
| `ERR_PILOT_RUN_NOT_FOUND` | 404 |
| `ERR_SHELF_LIFE_STUDY_NOT_FOUND` | 404 |
| `ERR_LABEL_APPROVAL_NOT_FOUND` | 404 |
| `ERR_RETAILER_NOT_FOUND` | 404 |
| `ERR_RESET_WINDOW_NOT_FOUND` | 404 |
| `ERR_PRESENTATION_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_PROJECT_VERSION_CONFLICT` | 412 |
| `ERR_FORMULATION_VERSION_CONFLICT` | 412 |
| `ERR_PROJECT_INVALID_STATE` | 409 |
| `ERR_GATE_REVIEW_INVALID_STATE` | 409 |
| `ERR_DELIVERABLE_INVALID_STATE` | 409 |
| `ERR_BUSINESS_CASE_INVALID_STATE` | 409 |
| `ERR_FORMULATION_INVALID_STATE` | 409 |
| `ERR_PILOT_RUN_INVALID_STATE` | 409 |
| `ERR_STUDY_INVALID_STATE` | 409 |
| `ERR_LABEL_INVALID_STATE` | 409 |
| `ERR_PRESENTATION_INVALID_STATE` | 409 |
| `ERR_SELF_APPROVAL_FORBIDDEN` | 403 |
| `ERR_OWNER_CANNOT_VOTE` | 403 |
| `ERR_CHAIR_CANNOT_VOTE_AND_CLOSE` | 403 |
| `ERR_GATE_SEQUENCE_VIOLATION` | 409 |
| `ERR_GATE_REVIEW_ALREADY_IN_SESSION` | 409 |
| `ERR_GATE_CONDITIONS_OPEN` | 409 |
| `ERR_QUORUM_NOT_MET` | 409 |
| `ERR_DUPLICATE_FUNCTION_VOTE` | 409 |
| `ERR_PREREQUISITE_NOT_SATISFIED` | 409 |
| `ERR_DELIVERABLE_CYCLE` | 409 |
| `ERR_REGULATORY_WAIVER_FORBIDDEN` | 409 |
| `ERR_DUPLICATE_DELIVERABLE_TYPE` | 409 |
| `ERR_DUPLICATE_CHANNEL_LINE` | 409 |
| `ERR_DUPLICATE_RESOURCE` | 409 |
| `ERR_PILOT_LINE_CONFLICT` | 409 |
| `ERR_RESET_WINDOW_CAPACITY_FULL` | 409 |
| `ERR_WINDOW_RETAILER_MISMATCH` | 409 |
| `ERR_WINDOW_CATEGORY_MISMATCH` | 409 |
| `ERR_CHANNEL_NOT_FORECAST` | 409 |
| `ERR_FORMULATION_PROJECT_MISMATCH` | 409 |
| `ERR_LABEL_NOT_APPROVED` | 409 |
| `ERR_NO_LOCKED_BUSINESS_CASE` | 409 |
| `ERR_PERIOD_SEQUENCE_VIOLATION` | 409 |
| `ERR_PRESENTATION_LEAD_TIME_VIOLATION` | 409 |
| `ERR_LAUNCH_DATE_OUTSIDE_WINDOW` | 409 |
| `ERR_LOCK_LEAD_TIME_VIOLATION` | 409 |
| `ERR_LAUNCH_DATE_NOT_REACHED` | 409 |
| `ERR_PRESENTATION_NOT_DUE` | 409 |
| `ERR_PILOT_RUN_NOT_DUE` | 409 |
| `ERR_TIMEPOINT_OUT_OF_ORDER` | 409 |
| `ERR_CONDITIONS_DUE_PASSED` | 409 |
| `ERR_CONDITIONS_NOT_DUE` | 409 |
| `ERR_DELIVERABLE_CHECKLIST_INCOMPLETE` | 422 |
| `ERR_GATE_READINESS_BELOW_FLOOR` | 422 |
| `ERR_ACCEPTED_SKU_EXCEEDS_PROPOSED` | 422 |
| `ERR_LAUNCH_READINESS_INCOMPLETE` | 422 |
| `ERR_UNSUPPORTED_CLAIMS_REQUIRED` | 422 |
| `ERR_DEV_BUDGET_EXCEEDED` | 422 |
| `ERR_BUSINESS_CASE_HURDLE_NOT_MET` | 422 |
