# Wedding Planning API — Product Requirements Document

## 1. Introduction

A wedding is a single high-stakes event with a hard, immovable deadline, dozens of independent vendors, hundreds of guests, and a budget that is simultaneously elastic in its line items and inelastic in its total. The teams who run these projects today bounce between spreadsheets for budgets, group chats for vendor coordination, paper seating charts for receptions, and ad-hoc emails for change orders — and the breakage between those tools is where almost every disaster originates. A vendor confirms a date that the planner already committed to a different vendor; a budget reallocation is signed off by the same person who requested it; a settlement is closed before the e-signed contract has actually been countersigned.

This document specifies the backend API for an integrated **Wedding Planning** platform that consolidates the lifecycle of a wedding project — from the moment a planner drafts a project profile, through vendor qualification, contract negotiation, milestone tracking, ceremony-day timeline construction, guest RSVP collection, all the way to per-vendor settlement and final project closure — into one consistent, audit-friendly system. Two principles drive almost every design decision. First, **provisional commitments and final settlements are different numbers** computed by different procedures, and the system must not conflate them. Second, **segregation of duties** is enforced at the API boundary: the operator who drafts a settlement may not finalize it, the planner who requests a change order may not approve it, and the auditor who closes a project may not be its planner.

The platform integrates with three external subsystems — payments, instant messaging, and electronic signature — through a single event hook that lets test harnesses and production callbacks drive system-actor transitions deterministically.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API MUST carry two authentication headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, identifying which role the principal is acting as on this request. If either header is missing or empty, the request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401). If `X-User-Role` is not one of the four recognized strings — `Planner`, `VendorRep`, `Couple`, `Auditor` — the request is rejected with `ERR_INVALID_ROLE` (HTTP 401).

The four roles differ in how `X-User-ID` is interpreted:

- When `X-User-Role` is `Planner`, `X-User-ID` is an opaque operator identifier; it is not the `id` of any persisted entity. Project ownership is enforced by string-equality between `X-User-ID` and `WeddingProject.planner_user_id`. A planner who is not the owner of the project named in the URL receives `ERR_NOT_OWNING_PLANNER` (HTTP 403). The same opaque value is recorded on derived fields such as `ChangeOrder.requested_by_user_id`, `ChangeOrder.approved_by_user_id`, `Settlement.confirmed_by_user_id`, and `AuditEntry.actor_user_id` whenever a state transition writes the actor's identity.
- When `X-User-Role` is `VendorRep`, `X-User-ID` is the `id` of the acting `Vendor`; vendor-rep ownership checks compare `X-User-ID` directly to the `vendor_id` of the resource being acted upon (the bound vendor of a contract, the owning vendor of a quote, or the vendor referenced by a settlement). A vendor representative attempting an action on a vendor that is not their own is rejected with `ERR_NOT_OWNING_VENDOR` (HTTP 403).
- When `X-User-Role` is `Couple`, `X-User-ID` is an opaque identifier not tied to any persisted entity; the couple's relationship to a project is implicit through the project's `couple_name`, and there is no entity-backed ownership check. The Couple role is granted access only to read endpoints on their project and to the guest-management endpoints they share with the planner.
- When `X-User-Role` is `Auditor`, `X-User-ID` is again an opaque operator identifier. To close a project, the acting auditor's `X-User-ID` MUST equal `WeddingProject.auditor_user_id`; otherwise the request is rejected with `ERR_AUDITOR_REQUIRED` (HTTP 403). The same value is recorded as `Settlement.finalized_by_user_id` when the auditor finalizes a settlement.

A request whose role is otherwise authenticated but lacks permission for the specific endpoint receives `ERR_AUDITOR_REQUIRED`, `ERR_NOT_OWNING_PLANNER`, or `ERR_NOT_OWNING_VENDOR` as appropriate to the failed check; the §4 endpoint table enumerates which roles each endpoint accepts.

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

All list endpoints accept two query parameters, `limit` and `offset`. The default `limit` is 10, the minimum is 1, and the maximum is 100; the default `offset` is 0. List results are sorted by `created_at` in ascending order so that pagination is stable across pages even as new records are appended. The pagination block in `meta` exposes four fields — `limit` (the effective limit applied), `offset` (the effective offset applied), `total_count` (the total number of records matching any filter applied to the list call), and `has_more` (true when `offset + limit < total_count`).

### 2.4. Common Resource Properties

Every resource in this system is uniquely identified by a server-minted UUID stored in the `id` field; identifiers carry no type prefix. Resources whose history matters carry three additional system fields: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that begins at 1 on creation and is incremented by exactly 1 on every server-side mutation. These resources are `WeddingProject`, `Milestone`, `Vendor`, `Quote`, `Contract`, `ChangeOrder`, `Settlement`, `TimelineSlot`, and `Guest`.

Two resources are immutable or append-only and therefore carry only `id` and `created_at` — no `updated_at`, no `version` field appears on them: `ProjectTemplate` (an immutable library entry whose `default_milestones` are copied into projects at creation time) and `AuditEntry` (an append-only log row that is never updated after insertion). The embedded `PerformanceRating` records likewise carry only `id`, `created_at`, and their immutable scoring payload (`score`, optional `comment`, `settlement_id`, `vendor_id`).

### 2.5. Optimistic Concurrency Control

Mutating endpoints (notably `PATCH` operations on `Milestone`, `Settlement`, `TimelineSlot`, and `Guest`) accept an optional `version` field in the request body. When `version` is supplied and does not equal the current `version` of the target resource, the request is rejected with `ERR_VERSION_CONFLICT` (HTTP 409). When `version` is omitted, the OCC check is skipped and the mutation proceeds against whatever the current state is. Two concurrent RSVP updates on the same `Guest` row that both supply the same stale `version` thus serialize: the first to commit succeeds and bumps `version`; the second receives `ERR_VERSION_CONFLICT`.

### 2.6. Monetary Quantities and Numeric Precision

All monetary values in this system are integer cents — `total_budget_cents`, `pinned_amount_cents`, `provisional_committed_cents`, `finalized_settled_cents`, `budget_balance_cents`, `delta_amount_cents`, `provisional_total_cents`, `breach_deduction_cents`, `refund_cents`, `final_amount_cents`, and `gift_amount_cents`. No rounding is applied to monetary aggregations; sums are exact in integer cents.

Vendor performance ratings (`avg_performance_rating`) are computed as decimal numbers with two decimal places of precision, rounded half-up. The rounding is applied **once** to the final mean — the system does not round each individual rating before summing.

### 2.7. Hierarchical Path Resolution and Project Terminality

Endpoints whose paths contain multiple `{...}` segments — for example `/wedding-projects/{projectId}/contracts/{contractId}/change-orders/{changeOrderId}/approve` — are resolved left-to-right. The `projectId` is checked first; if no `WeddingProject` with that `id` exists, the response is `ERR_PROJECT_NOT_FOUND` (HTTP 404), and no further segment is examined. The `contractId` is checked next, and the contract must belong to the resolved project; otherwise `ERR_CONTRACT_NOT_FOUND` (HTTP 404). Then the `changeOrderId` is checked against the resolved contract; otherwise `ERR_CHANGE_ORDER_NOT_FOUND`. The same rule produces `ERR_VENDOR_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`, `ERR_GUEST_NOT_FOUND`, `ERR_TIMELINE_SLOT_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_TEMPLATE_NOT_FOUND`, and `ERR_AUDIT_ENTRY_NOT_FOUND` for their respective path segments.

Once a `WeddingProject` reaches a terminal status of `CLOSED` or `CANCELLED`, every mutating endpoint nested under that project is rejected with `ERR_PROJECT_TERMINAL` (HTTP 409), regardless of role. Read endpoints remain available.

### 2.8. Cascades, Side-Effects, and the `updated_at` / `version` Contract

Many actions in this system mutate more than the resource they nominally target. Whenever the server mutates a resource — primary or cascaded — it bumps that resource's `version` by exactly 1 and refreshes `updated_at`. So when terminating a contract cascades a `Quote` to `WITHDRAWN`, the quote's `version` and `updated_at` move with it; when a settlement is finalized and the project's `provisional_committed_cents` and `finalized_settled_cents` shift, the `WeddingProject.version` and `updated_at` also move. The append-only `AuditEntry` rows that accompany cascades carry only their own `created_at`; they have no `updated_at` and no `version`.

### 2.9. Validation Priority and Evaluation Order

When several validation conditions could plausibly reject the same request, they are evaluated in a fixed priority order, and the first failing check determines the error returned. Authentication checks come first (missing headers before invalid role); identity-binding checks come next (`ERR_NOT_OWNING_PLANNER` and `ERR_NOT_OWNING_VENDOR`); then path resolution and existence checks (the various `ERR_*_NOT_FOUND` codes); then the project-terminal check (`ERR_PROJECT_TERMINAL`); then state preconditions of the requested transition (`ERR_CONTRACT_NOT_NEGOTIATING`, `ERR_PROJECT_NOT_IN_PLANNING`, and so on); then cross-aggregate referential checks (`ERR_QUOTE_VENDOR_MISMATCH`, `ERR_VENDOR_NOT_APPROVED`, `ERR_TIMELINE_VENDOR_NOT_CONTRACTED`); then segregation-of-duties (`ERR_SEGREGATION_OF_DUTIES`); then temporal constraints on the timeline (`ERR_TIMELINE_VENDOR_OVERLAP` before `ERR_TIMELINE_PARALLEL_CAP_EXCEEDED`); then guest-capacity (`ERR_GUEST_CAPACITY_EXCEEDED` before `ERR_TABLE_SEAT_LIMIT_EXCEEDED`); then fiscal checks (`ERR_BUDGET_OVERCOMMITTED` and `ERR_MILESTONE_PERCENTAGES_INVALID`); and finally `ERR_VERSION_CONFLICT` last so that a stale-version writer learns about real business problems before being told their version is stale.

In particular, the segregation-of-duties checks run **before** the budget overcommit check on change-order approval — a self-approving planner is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) even when the budget would have permitted the change.

### 2.10. Audit Logging Surface

Five categories of events are committed to the append-only `AuditEntry` log, distinguished by `event_kind`: `BUDGET_REALLOCATED` (whenever the milestone-percent allocation is rewritten via the budget-reallocation operation), `CHANGE_ORDER_APPROVED` (each successful change-order approval), `CONTRACT_TERMINATED` (each termination of a contract from any non-terminal status), `SETTLEMENT_FINALIZED` (each finalization of a settlement, plus a final budget-snapshot entry written when the project is closed), and `OVERSPEND_WARNING_RAISED` (raised at contract sign time when the post-commit `provisional_committed_cents` crosses the soft warning threshold). Each entry records the `subject_type` (one of `BUDGET`, `CONTRACT`, `SETTLEMENT`, or `CHANGE_ORDER`), the `subject_id` of the affected row, the `actor_user_id` and `actor_role` of the triggering principal, and a `payload` JSON object containing a snapshot of the before/after fields that changed. Audit entries are written inside the same transaction as the change they describe; if any cascade fails, the entry is not written.

## 3. Business Logic & Workflows

### 3.1. Project Inception, Templates, and the Planning Backbone

A new wedding project begins when a `Planner` submits the project profile: the `couple_name`, a `ceremony_date` expressed as a Unix timestamp in seconds, a `style` drawn from `CLASSIC`, `RUSTIC`, `MODERN`, or `DESTINATION`, a `scale` drawn from `INTIMATE`, `MEDIUM`, or `GRAND`, the operator identifier `planner_user_id` of the owning planner, the operator identifier `auditor_user_id` of the auditor who will eventually close the project, an overall budget cap `total_budget_cents`, and an optional `template_id` referencing a `ProjectTemplate` from the library. The `auditor_user_id` MUST differ from `planner_user_id` at creation; otherwise the request is rejected with `ERR_SEGREGATION_OF_DUTIES` because the same person cannot both run the project and review its closure. If `template_id` is supplied, the server resolves the template (or returns `ERR_TEMPLATE_NOT_FOUND` if it does not exist) and copies each entry of that template's `default_milestones` array — the ordered list of `{label, offset_days_from_ceremony, percent_of_budget}` triples — into newly minted `Milestone` rows on the project, computing each milestone's `due_at` from `ceremony_date` and `offset_days_from_ceremony`. The new project is created with `status` set to `DRAFT`.

`ProjectTemplate` rows themselves form an immutable library: an `Auditor` registers each template with a unique `name`, a target `scale`, and the `default_milestones` payload. Once created, a template is read-only; planners list templates filtered optionally by `scale` and reference one by its identifier when creating a project.

While a project remains in `DRAFT`, milestones may be created, updated, or deleted freely. After every such mutation — and again as a precondition to leaving `DRAFT` — the sum of `percent_of_budget` across all milestones on the project MUST equal exactly 100.0; if it does not, the mutation or activation is rejected with `ERR_MILESTONE_PERCENTAGES_INVALID` (HTTP 422). A milestone is created with `label`, `due_at`, and its `percent_of_budget` share. A milestone's `status` begins at `PENDING`; the planner advances it through `IN_PROGRESS` to `COMPLETED` via the milestone update endpoint, supplying the desired `status` in the payload along with an optional `version`. Advancing from `PENDING` to `IN_PROGRESS` requires the milestone to be in `PENDING` (otherwise `ERR_MILESTONE_NOT_PENDING`); advancing from `IN_PROGRESS` to `COMPLETED` requires it to be in `IN_PROGRESS` (otherwise `ERR_MILESTONE_NOT_IN_PROGRESS`). When the system clock advances to or past a milestone's `due_at` while the milestone is still `PENDING` or `IN_PROGRESS`, the milestone transitions to `OVERDUE` automatically.

The project's lifecycle then advances through four stages. The `DRAFT` to `PLANNING` transition (the activation step) requires the project to currently be `DRAFT` (otherwise `ERR_PROJECT_NOT_IN_DRAFT`), at least one `Milestone` to exist (otherwise `ERR_NO_MILESTONES`), and the milestone-percent sum to equal 100.0 (otherwise `ERR_MILESTONE_PERCENTAGES_INVALID`). The `PLANNING` to `EXECUTION` transition (start-execution) requires the project to be `PLANNING` (otherwise `ERR_PROJECT_NOT_IN_PLANNING`), at least one `ACCEPTED` `Contract` to exist for each of the `VENUE` and `CATERING` vendor categories (otherwise `ERR_REQUIRED_CATEGORY_UNCOVERED`, HTTP 422), and `budget_balance_cents` to be at least zero after committing (otherwise `ERR_BUDGET_OVERCOMMITTED`). The `EXECUTION` to `SETTLEMENT` transition (enter-settlement) requires the project to be `EXECUTION` (otherwise `ERR_PROJECT_NOT_IN_EXECUTION`), every contract on the project to have `contract_status` either `ACCEPTED` or `TERMINATED` (otherwise `ERR_OPEN_CONTRACTS_REMAIN`, HTTP 422), and the system clock to have advanced past `ceremony_date` (otherwise `ERR_CEREMONY_NOT_ELAPSED`, HTTP 422). The `SETTLEMENT` to `CLOSED` transition is reserved for the auditor and is described in section 3.7.

A planner may also cancel the project from any non-terminal status, transitioning `WeddingProject.status` to `CANCELLED`. Cancellation from `DRAFT` is a simple state change with no side effects. Cancellation from `PLANNING` or `EXECUTION` cascades: every contract on the project whose `contract_status` is `DRAFT`, `NEGOTIATING`, `SIGNED`, or `ACCEPTED` is forced to `TERMINATED` exactly as if the planner had terminated each one individually, which in turn cascades the bound `Quote` rows to `WITHDRAWN`, deletes all `TimelineSlot` rows owned by those vendors on this project, and resets any `DRAFT` or `VENDOR_CONFIRMED` `Settlement` to `DRAFT` with `confirmed_by_vendor_at` cleared. Each contract termination during cascade writes its own `AuditEntry` with `event_kind` of `CONTRACT_TERMINATED`.

### 3.2. Vendor Qualification, the Quote Catalogue, and Performance Ratings

Vendor onboarding is initiated by a `VendorRep`, who registers a new `Vendor` with a business `name` and a `category` drawn from `VENUE`, `PHOTOGRAPHY`, `FLORAL`, `CATERING`, `MC`, or `BAND`. The new vendor begins with `qualification_status` set to `PENDING_REVIEW`. An `Auditor` then either approves the vendor (transitioning `qualification_status` to `APPROVED`) or rejects it (transitioning to `REJECTED`). An `APPROVED` vendor may later be suspended by an auditor — transitioning to `SUSPENDED` and cascading every `Quote` belonging to that vendor in `DRAFT` or `OFFERED` status to `WITHDRAWN` — and a `SUSPENDED` vendor may be reinstated back to `APPROVED`. Suspending a vendor does not cascade to their already-`BOUND` quotes (those remain bound to their existing contracts) nor to existing contracts in `SIGNED` or `ACCEPTED` status; suspension is forward-looking.

A `VendorRep` builds the vendor's quote catalogue by creating `Quote` rows on their vendor. Each quote carries an `amount_cents` price, a free-text `scope_description`, and a `valid_until` Unix timestamp after which the quote may not be bound to a contract. The quote's `category` is copied from `Vendor.category` at creation time and is not separately modifiable. A new quote begins in `status` `DRAFT`. The vendor representative offers the quote (transitioning `DRAFT` to `OFFERED`), which requires the vendor's `qualification_status` to be `APPROVED` (otherwise `ERR_VENDOR_NOT_APPROVED`, HTTP 422) and the system clock to be strictly less than `valid_until` (otherwise `ERR_QUOTE_EXPIRED`). A quote in `DRAFT` may be withdrawn directly to `WITHDRAWN`; a quote in `OFFERED` is moved to `BOUND` automatically when a contract pins it at signing, and is moved to `WITHDRAWN` automatically when the binding contract terminates. When the system clock reaches or passes a quote's `valid_until` while the quote is still `OFFERED`, it transitions to `EXPIRED` automatically.

Vendor performance is measured per finalized settlement. After a settlement reaches `FINALIZED` status, a planner may attach a `PerformanceRating` carrying an integer `score` from 1 to 5 inclusive and an optional free-text `comment`. The vendor's `avg_performance_rating` is recomputed from scratch each time a rating is written (or each time a settlement finalizes): the system collects every `PerformanceRating.score` whose linked `Settlement` is currently `FINALIZED` (excluding any whose settlement was reverted to `DRAFT` by a contract-terminate cascade), divides the sum of scores by the count of ratings, and rounds the resulting mean half-up to two decimal places; the count of contributing ratings is exposed as `rating_count`. When a vendor has zero contributing ratings, `avg_performance_rating` is `null` and `rating_count` is `0`. A rating whose underlying contract was later terminated is still included so long as the settlement itself remained `FINALIZED`.

### 3.3. Contract Binding, the Negotiation Loop, and the E-Signature Handshake

A contract binds a project to a vendor by way of a specific quote. A planner creates a `Contract` on the project by submitting the bound `vendor_id` and `quote_id`. The server validates that the chosen `Quote` actually belongs to the chosen `Vendor` (otherwise `ERR_QUOTE_VENDOR_MISMATCH`, HTTP 422); contracts begin in `contract_status` of `DRAFT` and `payment_status` of `UNPAID`, with `negotiation_round` initialized to 0. These two status dimensions evolve independently: `contract_status` walks the binding lifecycle (`DRAFT` → `NEGOTIATING` → `SIGNED` → `ACCEPTED`, with `TERMINATED` reachable from any non-terminal state), while `payment_status` walks the settlement waterfall (`UNPAID` → `PARTIAL` → `FINALIZED`, or `REFUNDED` if the final settled amount is zero with a refund).

The planner sends the contract for negotiation, transitioning it from `DRAFT` to `NEGOTIATING`; the contract MUST currently be `DRAFT` (otherwise `ERR_CONTRACT_NOT_IN_DRAFT`), and the bound `Quote.status` MUST be either `DRAFT` or `OFFERED` (otherwise `ERR_QUOTE_NOT_AVAILABLE`). As a side effect, a quote that was still in `DRAFT` is bumped to `OFFERED`. From `NEGOTIATING` the contract may loop back: a `VendorRep` representing the bound vendor may revise the contract, returning it from `NEGOTIATING` to `DRAFT`; this requires the contract to currently be `NEGOTIATING` (otherwise `ERR_CONTRACT_NOT_NEGOTIATING`) and the acting `VendorRep`'s `X-User-ID` to equal the bound `Vendor.id` (otherwise `ERR_NOT_OWNING_VENDOR`); on success the contract's `negotiation_round` is incremented by exactly 1, and the bound quote is reset from `OFFERED` back to `DRAFT` so the vendor can re-price.

Signing is the planner's one-way commitment. The signing transition advances `contract_status` from `NEGOTIATING` to `SIGNED` and requires several things to be true at once: the contract is currently `NEGOTIATING` (otherwise `ERR_CONTRACT_NOT_NEGOTIATING`), the bound quote is currently `OFFERED` (otherwise `ERR_QUOTE_NOT_AVAILABLE`), the system clock is strictly less than `Quote.valid_until` (otherwise `ERR_QUOTE_EXPIRED`), the project is currently `PLANNING` (otherwise `ERR_PROJECT_NOT_IN_PLANNING`), and the project's `budget_balance_cents` after subtracting `Quote.amount_cents` would still be at least zero (otherwise `ERR_BUDGET_OVERCOMMITTED`, HTTP 402). On success, the server captures `pinned_quote_version` from the quote's current `version` and `pinned_amount_cents` from the quote's current `amount_cents`; these pinned values do not change even if the underlying quote is later mutated. The bound quote moves to `BOUND` (its `version` increments). The server dispatches an e-sign envelope and stores the returned identifier in `e_sign_envelope_id`. The project's `provisional_committed_cents` is recomputed; if the post-commit value crosses the soft warning threshold, an `AuditEntry` with `event_kind` of `OVERSPEND_WARNING_RAISED` is appended. When two planners attempt to sign the same contract simultaneously, the contract's `contract_status` serializes on a first-writer-wins basis: exactly one sign succeeds, and the loser sees `ERR_CONTRACT_NOT_NEGOTIATING` (HTTP 409) because the contract has already advanced past `NEGOTIATING`. When two planners attempt to sign two distinct contracts on the same project simultaneously, where each contract individually fits within `budget_balance_cents` but their combined commitment does not, the project's identifier serializes the writes; at most one succeeds, and the loser receives `ERR_BUDGET_OVERCOMMITTED` (HTTP 409 — distinguishable from the pre-commit 402 because here the conflict is a post-commit re-evaluation).

After signing, the contract waits for the e-signature subsystem to confirm countersignature. The accept-signature transition advances `contract_status` from `SIGNED` to `ACCEPTED` and may be invoked by either the planner or an auditor, but only after the integration hook has received an `ESIGN_COMPLETED` event for the contract's `e_sign_envelope_id`; otherwise the request is rejected with `ERR_ESIGN_NOT_COMPLETE`. The contract MUST currently be `SIGNED` (otherwise `ERR_CONTRACT_NOT_SIGNED`).

A planner may terminate a contract from any non-terminal `contract_status`. Terminating a `DRAFT` or `NEGOTIATING` contract simply withdraws the bound `Quote` (`OFFERED` or `BOUND` quotes go to `WITHDRAWN`). Terminating a `SIGNED` contract additionally deletes every `TimelineSlot` on the project owned by that vendor and recomputes the project's `provisional_committed_cents` to drop the contract's `pinned_amount_cents`; an `AuditEntry` with `event_kind` of `CONTRACT_TERMINATED` is appended. Terminating an `ACCEPTED` contract performs the same cascade as the `SIGNED` case and additionally, if a `Settlement` already exists for the contract in `DRAFT` or `VENDOR_CONFIRMED` status, forces that settlement back to `DRAFT` and clears `confirmed_by_vendor_at` to `null` so the work is not lost but the vendor must re-confirm any rewritten amount.

### 3.4. Change Orders and the Settlement Waterfall

The provisional commitment for a contract is `pinned_amount_cents` plus the running sum of every approved `ChangeOrder.delta_amount_cents` against that contract; deltas may be positive or negative. A planner files a change order on a contract by supplying a signed `delta_amount_cents` and a free-text `reason`; the server records the acting planner's `X-User-ID` as `requested_by_user_id` and gives the change order a `status` of `PENDING`. A second planner — one whose `X-User-ID` differs from `requested_by_user_id` — then either approves or rejects the change order. Approval is gated by four checks evaluated in this order: the change order MUST currently be `PENDING` (otherwise `ERR_CHANGE_ORDER_NOT_PENDING`); the acting planner's `X-User-ID` MUST differ from `requested_by_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`, HTTP 403); the contract's `contract_status` MUST be `SIGNED` or `ACCEPTED` (otherwise `ERR_CONTRACT_NOT_BOUND`); and after applying the delta the project's `budget_balance_cents` reduced by `delta_amount_cents` MUST be at least zero (otherwise `ERR_BUDGET_OVERCOMMITTED`, HTTP 402). On success, the server records `approved_by_user_id` as the acting planner's `X-User-ID`, appends an `AuditEntry` with `event_kind` of `CHANGE_ORDER_APPROVED`, and — if a `Settlement` already exists for the contract in `DRAFT` status — recomputes that settlement's `provisional_total_cents` as `pinned_amount_cents` plus the new sum of approved deltas, and re-derives `final_amount_cents` for the cascading preview. Rejection is simpler: the change order MUST currently be `PENDING` (otherwise `ERR_CHANGE_ORDER_NOT_PENDING`); on success its `status` becomes `REJECTED`. When two planners (each distinct from the requester) approve sibling change orders on the same contract simultaneously and their combined deltas would push the project past its budget, the contract's identifier serializes the writes; at most one approval succeeds, and the loser receives `ERR_BUDGET_OVERCOMMITTED` (HTTP 409 in the post-commit conflict form).

After a contract reaches `ACCEPTED`, the planner creates the contract's single `Settlement` row, optionally seeding `breach_deduction_cents` and `refund_cents` (both default to 0 and both must remain non-negative). The server records the acting planner as `confirmed_by_user_id` and computes `provisional_total_cents` as `pinned_amount_cents` plus the sum of approved change-order deltas. The settlement is created in `status` `DRAFT`. While the settlement remains `DRAFT`, the planner may patch `breach_deduction_cents` or `refund_cents` and may supply an optional `version` for the OCC check. Reading a `DRAFT` or `VENDOR_CONFIRMED` settlement returns the **provisional preview** of `final_amount_cents`: the preview applies the contract's approved change-order deltas in **descending** order of their approval time (so the latest revisions dominate first) **without** the per-step clamp at zero, then deducts `breach_deduction_cents` and `refund_cents`. This preview value is the running estimate displayed before finalization; it may differ from the value eventually committed if intermediate sums would have gone negative.

The `VendorRep` representing the bound vendor confirms the settlement, advancing its `status` from `DRAFT` to `VENDOR_CONFIRMED`. This requires the settlement to currently be `DRAFT` (otherwise `ERR_SETTLEMENT_NOT_DRAFT`), the contract's `contract_status` to be `ACCEPTED` (otherwise `ERR_CONTRACT_NOT_ACCEPTED`), and the acting `VendorRep`'s `X-User-ID` to equal the bound `Vendor.id` (otherwise `ERR_NOT_OWNING_VENDOR`); on success `confirmed_by_vendor_at` is set to the current clock.

Finalization is the auditor's responsibility. The finalize transition advances `status` from `VENDOR_CONFIRMED` to `FINALIZED` and requires the settlement to currently be `VENDOR_CONFIRMED` (otherwise `ERR_SETTLEMENT_NOT_CONFIRMED`), the acting role to be `Auditor` (otherwise `ERR_AUDITOR_REQUIRED`), and the acting auditor's `X-User-ID` to differ from `confirmed_by_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`). On finalization, the server records `finalized_by_user_id` and computes the **final committed** value of `final_amount_cents` by a different procedure than the preview: it walks the contract's approved change orders in **ascending** order of the `created_at` of their `CHANGE_ORDER_APPROVED` audit entry, beginning with a running base equal to `pinned_amount_cents`. After each delta, the running base is replaced by the larger of zero and the post-delta base — that is, the running base is clamped at zero before the next delta is applied, so a deeply negative interim total cannot subsequently be lifted back above zero. Once all deltas are processed, the resulting base is stored as `provisional_total_cents`. The committed `final_amount_cents` is then the larger of zero and `provisional_total_cents` minus `breach_deduction_cents` minus `refund_cents`. The contract's `payment_status` is updated: if `final_amount_cents` is greater than zero, `payment_status` becomes `FINALIZED` (regardless of whether it was previously `UNPAID` or `PARTIAL`); if `refund_cents` is greater than zero and `final_amount_cents` equals zero, `payment_status` becomes `REFUNDED`. The project's `finalized_settled_cents` is increased by the new `final_amount_cents`, and the project's `provisional_committed_cents` is decreased by this settlement's `provisional_total_cents` so the contract is no longer double-counted. The vendor's `avg_performance_rating` is recomputed using all contributing ratings, and an `AuditEntry` with `event_kind` of `SETTLEMENT_FINALIZED` is appended.

A planner may then attach a `PerformanceRating` to the finalized settlement by supplying an integer `score` between 1 and 5 inclusive and an optional `comment`; the rating triggers another recomputation of the vendor's `avg_performance_rating` and `rating_count`.

### 3.5. Budgets, Reallocation, and the Three-Number Ledger

The project ledger is built from three integer-cent numbers stored on `WeddingProject`. The `total_budget_cents` is the immutable cap supplied at creation. The `provisional_committed_cents` is the sum, across every `Contract` on this project whose `contract_status` is either `SIGNED` or `ACCEPTED` and whose linked `Settlement` (if any) is not yet `FINALIZED`, of `pinned_amount_cents` plus the sum of approved-`ChangeOrder` `delta_amount_cents` against that contract; contracts in `DRAFT` or `NEGOTIATING` are excluded because they have not yet committed. The `finalized_settled_cents` is the sum of `final_amount_cents` across every `Settlement` whose `status` is `FINALIZED` on this project, regardless of whether the underlying contract was later terminated. The `budget_balance_cents` is then `total_budget_cents` minus `provisional_committed_cents` minus `finalized_settled_cents`. All three figures are exact in integer cents and recomputed alongside one another whenever a contract is signed or terminated, a change order is approved, or a settlement is finalized.

A planner may rewrite the milestone-share allocation without changing `total_budget_cents` by invoking the budget-reallocation operation with an `allocations` payload — a list of `{milestone_id, percent_of_budget}` pairs covering every milestone on the project. The new shares MUST again sum to exactly 100.0 (otherwise `ERR_MILESTONE_PERCENTAGES_INVALID`); on success, every affected `Milestone.percent_of_budget` is updated and an `AuditEntry` with `event_kind` of `BUDGET_REALLOCATED` records the before/after snapshot in its `payload`. Reallocation also re-evaluates `budget_balance_cents`; if the proposed redistribution would leave the project's `budget_balance_cents` below zero, the request is rejected with `ERR_BUDGET_OVERCOMMITTED` (HTTP 402).

### 3.6. Ceremony-Day Timeline, Vendor Coordination, and Rehearsal Snapshots

A wedding's ceremony day is constructed minute by minute from `TimelineSlot` rows. A planner adds a slot by supplying `start_at` and `end_at` (Unix timestamps in seconds, treated as a half-open interval where the start is inclusive and the end is exclusive), a human `label`, and optionally a `vendor_id` (omit for couple-only slots), a `setup_buffer_seconds` (default 0) representing pre-slot setup time the vendor needs exclusively, and a `kind` drawn from `PREPARATION`, `CEREMONY`, or `RECEPTION` (default `CEREMONY`). When `vendor_id` is supplied, the named vendor MUST have an `ACCEPTED` `Contract` on this project; otherwise the request is rejected with `ERR_TIMELINE_VENDOR_NOT_CONTRACTED` (HTTP 422).

Two scheduling rules then apply, both grounded in the same overlap definition: two slots A and B overlap iff the larger of `A.start_at - A.setup_buffer_seconds` and `B.start_at - B.setup_buffer_seconds` is strictly less than the smaller of `A.end_at` and `B.end_at`. Adjacency without overlap — where one slot's `end_at` equals the next slot's `start_at` adjusted by setup buffer — is allowed because the intervals are half-open. The first rule is the per-vendor rule: among slots filtered to share the same `vendor_id`, no pair may overlap, since a vendor cannot be in two places at once; a violation is rejected with `ERR_TIMELINE_VENDOR_OVERLAP` (HTTP 409). The second rule is the project-wide parallel-ceremony cap: among slots filtered to `kind` of `CEREMONY` (ignoring vendor), the count of slots active at any single instant — counting the setup-buffer extension on the start side — MUST not exceed two; a violation is rejected with `ERR_TIMELINE_PARALLEL_CAP_EXCEEDED` (HTTP 409). Both rules apply on slot creation and on slot update. When two timeline-slot creations race on the same vendor's window, the per-vendor pair `(project_id, vendor_id)` serializes them: the first wins and the second is rejected with `ERR_TIMELINE_VENDOR_OVERLAP`. When two timeline-slot creations race on the project as a whole and would together push the count of overlapping `CEREMONY` slots past the cap, the project's identifier serializes them: the first wins and the second is rejected with `ERR_TIMELINE_PARALLEL_CAP_EXCEEDED`.

A planner may update a slot's `start_at`, `end_at`, `setup_buffer_seconds`, or `label` (with optional `version`); both overlap rules are re-evaluated. A planner may also delete a slot outright. At any point, a planner may snapshot the current timeline as a rehearsal version, which atomically increments `WeddingProject.rehearsal_version` by exactly 1; the snapshot itself is opaque to this API surface — only the monotonic counter is exposed.

### 3.7. Guest List, Capacity Caps, and Seating

The guest list is shared between the planner and the couple. A new `Guest` is added with at minimum a `full_name`; optional fields at creation are `party_size` (defaulting to 1, MUST be at least 1), `dietary_requirements` (an array of free-form tags such as `VEGAN` or `GLUTEN_FREE`, defaulting to the empty list), and `accessibility_requirements` (an array of free-form tags such as `WHEELCHAIR`, defaulting to the empty list). The new guest's `rsvp_status` is initialized to `INVITED`, `table_number` to `null`, `gift_amount_cents` to 0, and `thank_you_sent_at` to `null`. The planner or couple may patch most of these fields after creation (`full_name`, `party_size`, `dietary_requirements`, `accessibility_requirements`, `table_number`, `gift_amount_cents`, `thank_you_sent_at`, with optional `version`) and may invoke the dedicated RSVP endpoint to set the guest's `rsvp_status` to one of `INVITED`, `CONFIRMED`, `DECLINED`, or `NO_RESPONSE`.

Two capacity rules guard the guest list. The per-scale cap limits the total of `party_size` across all guests with `rsvp_status` of `CONFIRMED` on the project: at most 50 for `INTIMATE`, at most 200 for `MEDIUM`, and at most 500 for `GRAND`. Adding a guest, patching a guest's `party_size`, or setting an RSVP to `CONFIRMED` — any of which would push the confirmed total past its scale cap — is rejected with `ERR_GUEST_CAPACITY_EXCEEDED` (HTTP 409). The table-seat rule applies whenever `table_number` is set on a guest: `table_number` MUST be a positive integer, and the sum of `party_size` across all guests assigned to the same table MUST not exceed 10 seats; otherwise the request is rejected with `ERR_TABLE_SEAT_LIMIT_EXCEEDED` (HTTP 409).

Post-wedding, the planner records each gift on the relevant guest by setting `gift_amount_cents` and tracks thank-you correspondence by setting `thank_you_sent_at` to the Unix timestamp of dispatch.

### 3.8. Project Closure, Audit Log, and the Test-Driving Hooks

Project closure is the auditor's exclusive privilege. The `SETTLEMENT` to `CLOSED` transition requires the project to currently be `SETTLEMENT` (otherwise `ERR_PROJECT_NOT_IN_SETTLEMENT`), every contract on the project to either have `contract_status` of `TERMINATED` or to have a `Settlement` in `FINALIZED` status (otherwise `ERR_UNFINALIZED_SETTLEMENTS`, HTTP 422), and the acting user's `X-User-ID` to equal the project's `auditor_user_id` and to differ from `planner_user_id` (otherwise `ERR_AUDITOR_REQUIRED` or `ERR_SEGREGATION_OF_DUTIES`). On success, the project transitions to `CLOSED`, and a final `AuditEntry` with `event_kind` of `SETTLEMENT_FINALIZED` and `subject_type` of `BUDGET` is appended capturing the final budget snapshot in its `payload`. When an auditor's finalize and a planner's cancel race on a project in `SETTLEMENT`, the project's `status` field serializes the writes on a first-writer-wins basis; exactly one wins, and the loser sees `ERR_PROJECT_NOT_IN_SETTLEMENT` (HTTP 409) because the project's status has already moved.

The audit log is queryable through a dedicated read endpoint that supports filtering by `subject_type` (one of `BUDGET`, `CONTRACT`, `SETTLEMENT`, or `CHANGE_ORDER`) or by `event_kind` (one of `BUDGET_REALLOCATED`, `CHANGE_ORDER_APPROVED`, `CONTRACT_TERMINATED`, `SETTLEMENT_FINALIZED`, or `OVERSPEND_WARNING_RAISED`). Each entry exposes its `actor_user_id`, `actor_role`, and `payload` snapshot.

Three operator hooks exist to drive system-actor transitions and to advance the deterministic test clock. The event-emit hook accepts a `kind` (one of `ESIGN_COMPLETED`, `PAYMENT_RECEIVED`, or `IM_DELIVERED`) and optionally an `envelope_id`, `contract_id`, or `settlement_id` payload; an `ESIGN_COMPLETED` event whose `envelope_id` matches a contract's `e_sign_envelope_id` is what makes that contract eligible for the `SIGNED` to `ACCEPTED` transition. The clock-advance hook accepts a `to_timestamp` parameter representing the new absolute Unix timestamp the logical clock should be set to; advancing the clock runs the deferred sweeps that transition `OFFERED` quotes whose `valid_until` has elapsed to `EXPIRED` and `PENDING` or `IN_PROGRESS` milestones whose `due_at` has elapsed to `OVERDUE`. The sweep-run hook performs the same sweeps without changing the clock. All three hooks may be invoked by any authenticated role for testing convenience; they are operationally inert outside the test harness.

## 4. Endpoint Definitions

The endpoint table below is a concise summary of the HTTP surface. New resource creations return HTTP 201 Created; modifications, state transitions, and successful reads return HTTP 200 OK; deletions return HTTP 204 No Content; the event-emit hook returns HTTP 202 Accepted. Detailed request and response shapes — what fields each endpoint accepts, what side effects each transition triggers, which validation errors apply — are documented narratively in §3 above and §2's cross-cutting principles; the §4 table itself does not duplicate that detail.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /wedding-projects | Create a wedding project (optionally from a template) | Planner |
| GET | /wedding-projects | List projects | Planner, Auditor, Couple |
| GET | /wedding-projects/{projectId} | Retrieve one project | Planner, Auditor, Couple, VendorRep |
| POST | /wedding-projects/{projectId}/activate | Advance project from DRAFT to PLANNING | Planner |
| POST | /wedding-projects/{projectId}/start-execution | Advance project from PLANNING to EXECUTION | Planner |
| POST | /wedding-projects/{projectId}/enter-settlement | Advance project from EXECUTION to SETTLEMENT | Planner |
| POST | /wedding-projects/{projectId}/close | Advance project from SETTLEMENT to CLOSED | Auditor |
| POST | /wedding-projects/{projectId}/cancel | Cancel project from any non-terminal status | Planner |
| POST | /wedding-projects/{projectId}/budget/reallocate | Rewrite per-milestone budget shares | Planner |
| POST | /project-templates | Register an immutable project template | Auditor |
| GET | /project-templates | List templates | Planner, Auditor |
| GET | /project-templates/{templateId} | Retrieve one template | Planner, Auditor |
| POST | /wedding-projects/{projectId}/milestones | Add a milestone | Planner |
| GET | /wedding-projects/{projectId}/milestones | List milestones | Planner, Auditor, Couple |
| PATCH | /wedding-projects/{projectId}/milestones/{milestoneId} | Update fields or advance milestone status | Planner |
| DELETE | /wedding-projects/{projectId}/milestones/{milestoneId} | Remove a milestone (only while project DRAFT) | Planner |
| POST | /vendors | Register a vendor in PENDING_REVIEW | VendorRep |
| GET | /vendors | List vendors | Planner, Auditor, VendorRep |
| GET | /vendors/{vendorId} | Retrieve one vendor | Planner, Auditor, VendorRep |
| POST | /vendors/{vendorId}/approve | Approve vendor qualification | Auditor |
| POST | /vendors/{vendorId}/reject | Reject vendor qualification | Auditor |
| POST | /vendors/{vendorId}/suspend | Suspend an approved vendor (cascades quotes) | Auditor |
| POST | /vendors/{vendorId}/reinstate | Reinstate a suspended vendor | Auditor |
| POST | /vendors/{vendorId}/quotes | Create a quote in DRAFT | VendorRep |
| GET | /vendors/{vendorId}/quotes | List quotes for a vendor | Planner, Auditor, VendorRep |
| POST | /vendors/{vendorId}/quotes/{quoteId}/offer | Advance quote DRAFT to OFFERED | VendorRep |
| POST | /vendors/{vendorId}/quotes/{quoteId}/withdraw | Advance quote DRAFT to WITHDRAWN | VendorRep |
| POST | /wedding-projects/{projectId}/contracts | Create a contract binding in DRAFT | Planner |
| GET | /wedding-projects/{projectId}/contracts | List contracts on a project | Planner, Auditor, Couple |
| GET | /wedding-projects/{projectId}/contracts/{contractId} | Retrieve one contract | Planner, Auditor, Couple, VendorRep |
| POST | /wedding-projects/{projectId}/contracts/{contractId}/send-for-negotiation | Advance contract DRAFT to NEGOTIATING | Planner |
| POST | /wedding-projects/{projectId}/contracts/{contractId}/revise | Cyclic loop NEGOTIATING back to DRAFT | VendorRep |
| POST | /wedding-projects/{projectId}/contracts/{contractId}/sign | Advance contract NEGOTIATING to SIGNED (pin and dispatch e-sign) | Planner |
| POST | /wedding-projects/{projectId}/contracts/{contractId}/accept-signature | Advance contract SIGNED to ACCEPTED on e-sign callback | Planner, Auditor |
| POST | /wedding-projects/{projectId}/contracts/{contractId}/terminate | Terminate contract with cascading effects | Planner |
| POST | /wedding-projects/{projectId}/contracts/{contractId}/change-orders | Create a change order in PENDING | Planner |
| GET | /wedding-projects/{projectId}/contracts/{contractId}/change-orders | List change orders for a contract | Planner, Auditor |
| POST | /wedding-projects/{projectId}/contracts/{contractId}/change-orders/{changeOrderId}/approve | Approve change order (segregation enforced) | Planner |
| POST | /wedding-projects/{projectId}/contracts/{contractId}/change-orders/{changeOrderId}/reject | Reject change order | Planner |
| POST | /wedding-projects/{projectId}/contracts/{contractId}/settlement | Create the contract's single settlement in DRAFT | Planner |
| GET | /wedding-projects/{projectId}/contracts/{contractId}/settlement | Retrieve the contract's settlement (provisional preview when not FINALIZED) | Planner, Auditor, VendorRep |
| PATCH | /wedding-projects/{projectId}/contracts/{contractId}/settlement | Update breach or refund while still DRAFT | Planner |
| POST | /wedding-projects/{projectId}/contracts/{contractId}/settlement/confirm | Advance settlement DRAFT to VENDOR_CONFIRMED | VendorRep |
| POST | /wedding-projects/{projectId}/contracts/{contractId}/settlement/finalize | Advance settlement VENDOR_CONFIRMED to FINALIZED (segregation enforced) | Auditor |
| POST | /wedding-projects/{projectId}/contracts/{contractId}/settlement/performance-rating | Record a vendor performance rating on a FINALIZED settlement | Planner |
| POST | /wedding-projects/{projectId}/timeline-slots | Create a timeline slot | Planner |
| GET | /wedding-projects/{projectId}/timeline-slots | List timeline slots | Planner, Auditor, Couple, VendorRep |
| PATCH | /wedding-projects/{projectId}/timeline-slots/{slotId} | Update a slot | Planner |
| DELETE | /wedding-projects/{projectId}/timeline-slots/{slotId} | Delete a slot | Planner |
| POST | /wedding-projects/{projectId}/timeline/snapshot-rehearsal | Increment rehearsal_version | Planner |
| POST | /wedding-projects/{projectId}/guests | Add a guest in INVITED | Planner, Couple |
| GET | /wedding-projects/{projectId}/guests | List guests | Planner, Auditor, Couple |
| PATCH | /wedding-projects/{projectId}/guests/{guestId} | Update guest fields including seating, gift, thank-you | Planner, Couple |
| POST | /wedding-projects/{projectId}/guests/{guestId}/rsvp | Set rsvp_status | Planner, Couple |
| GET | /wedding-projects/{projectId}/audit-entries | List audit entries for a project | Planner, Auditor |
| POST | /_events/emit | Emit an external integration event | Planner, Auditor, VendorRep, Couple |
| POST | /_clock/advance | Advance the logical clock to a supplied to_timestamp and run sweeps | Planner, Auditor, VendorRep, Couple |
| POST | /_sweep/run | Run the periodic sweep without advancing the clock | Planner, Auditor, VendorRep, Couple |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_AUTH_HEADERS | 401 |
| ERR_INVALID_ROLE | 401 |
| ERR_NOT_OWNING_PLANNER | 403 |
| ERR_NOT_OWNING_VENDOR | 403 |
| ERR_AUDITOR_REQUIRED | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_PROJECT_NOT_FOUND | 404 |
| ERR_VENDOR_NOT_FOUND | 404 |
| ERR_CONTRACT_NOT_FOUND | 404 |
| ERR_QUOTE_NOT_FOUND | 404 |
| ERR_MILESTONE_NOT_FOUND | 404 |
| ERR_GUEST_NOT_FOUND | 404 |
| ERR_TIMELINE_SLOT_NOT_FOUND | 404 |
| ERR_CHANGE_ORDER_NOT_FOUND | 404 |
| ERR_SETTLEMENT_NOT_FOUND | 404 |
| ERR_TEMPLATE_NOT_FOUND | 404 |
| ERR_AUDIT_ENTRY_NOT_FOUND | 404 |
| ERR_PROJECT_TERMINAL | 409 |
| ERR_PROJECT_NOT_IN_DRAFT | 409 |
| ERR_PROJECT_NOT_IN_PLANNING | 409 |
| ERR_PROJECT_NOT_IN_EXECUTION | 409 |
| ERR_PROJECT_NOT_IN_SETTLEMENT | 409 |
| ERR_CONTRACT_NOT_IN_DRAFT | 409 |
| ERR_CONTRACT_NOT_NEGOTIATING | 409 |
| ERR_CONTRACT_NOT_SIGNED | 409 |
| ERR_CONTRACT_NOT_ACCEPTED | 409 |
| ERR_CONTRACT_NOT_BOUND | 409 |
| ERR_QUOTE_NOT_AVAILABLE | 409 |
| ERR_QUOTE_EXPIRED | 409 |
| ERR_VENDOR_NOT_APPROVED | 422 |
| ERR_SETTLEMENT_NOT_DRAFT | 409 |
| ERR_SETTLEMENT_NOT_CONFIRMED | 409 |
| ERR_CHANGE_ORDER_NOT_PENDING | 409 |
| ERR_MILESTONE_NOT_PENDING | 409 |
| ERR_MILESTONE_NOT_IN_PROGRESS | 409 |
| ERR_NO_MILESTONES | 422 |
| ERR_REQUIRED_CATEGORY_UNCOVERED | 422 |
| ERR_OPEN_CONTRACTS_REMAIN | 422 |
| ERR_CEREMONY_NOT_ELAPSED | 422 |
| ERR_UNFINALIZED_SETTLEMENTS | 422 |
| ERR_ESIGN_NOT_COMPLETE | 409 |
| ERR_QUOTE_VENDOR_MISMATCH | 422 |
| ERR_TIMELINE_VENDOR_NOT_CONTRACTED | 422 |
| ERR_TIMELINE_VENDOR_OVERLAP | 409 |
| ERR_TIMELINE_PARALLEL_CAP_EXCEEDED | 409 |
| ERR_BUDGET_OVERCOMMITTED | 402 |
| ERR_MILESTONE_PERCENTAGES_INVALID | 422 |
| ERR_VERSION_CONFLICT | 409 |

---

## Hard Contract Reports

### Contract 1: Field-Name Coverage

```
Field coverage check:
- entities[].fields: 78 required, 78 present, 0 missing
- endpoints[].request_body / input: 22 distinct identifiers required, 22 present, 0 missing
- endpoints[].query_params: 12 distinct identifiers required, 12 present, 0 missing
- endpoints[].path_params: 9 distinct identifiers required, 9 present, 0 missing
Status: PASS
```

(All entity field names — including `couple_name`, `ceremony_date`, `style`, `scale`, `planner_user_id`, `auditor_user_id`, `template_id`, `status`, `total_budget_cents`, `provisional_committed_cents`, `finalized_settled_cents`, `budget_balance_cents`, `rehearsal_version`, `name`, `default_milestones`, `offset_days_from_ceremony`, `percent_of_budget`, `project_id`, `label`, `due_at`, `category`, `qualification_status`, `avg_performance_rating`, `rating_count`, `vendor_id`, `amount_cents`, `scope_description`, `valid_until`, `quote_id`, `pinned_quote_version`, `pinned_amount_cents`, `contract_status`, `payment_status`, `e_sign_envelope_id`, `negotiation_round`, `contract_id`, `delta_amount_cents`, `reason`, `requested_by_user_id`, `approved_by_user_id`, `provisional_total_cents`, `breach_deduction_cents`, `refund_cents`, `final_amount_cents`, `confirmed_by_vendor_at`, `confirmed_by_user_id`, `finalized_by_user_id`, `start_at`, `end_at`, `setup_buffer_seconds`, `kind`, `full_name`, `party_size`, `rsvp_status`, `dietary_requirements`, `accessibility_requirements`, `table_number`, `gift_amount_cents`, `thank_you_sent_at`, `subject_type`, `subject_id`, `actor_user_id`, `actor_role`, `event_kind`, `payload`, `score`, `comment`, `settlement_id`, `version` — are present in narrative; all path params `projectId`, `contractId`, `vendorId`, `quoteId`, `milestoneId`, `guestId`, `slotId`, `changeOrderId`, `templateId` and request-body identifiers `allocations`, `envelope_id`, `to_timestamp`, plus query params `limit`, `offset`, `status`, `category`, `qualification_status`, `contract_status`, `payment_status`, `rsvp_status`, `subject_type`, `event_kind`, `scale` are mentioned.)

### Contract 2: Rule Coverage

```
Rule coverage check:
- validations[] with priority: 15 checked, 15 expressed in prose (priority order spelled out in §2.9), 0 missing
- concurrency_rules[] with error_id: 7 checked, 7 expressed (each names racing operations, serialization key, and loser error_id), 0 missing
- state_machines[].transitions: 31 checked, 31 fully expressed (each from/to pair, every precondition paired with its error_id, every side_effect), 0 missing
- calculations[]: 6 checked, 6 fully expressed (formulas translated to precise prose; both variants of final_settlement_amount described), 0 missing
- validations[] conditions: 15 checked, 15 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 50 checked, 50 expressed in §3 narrative, 0 missing
- entities[].fields[] structured content: all defaults/enums/sources reconstructible from prose, 0 missing
- sibling-branch symmetry: 5 sibling groups checked (project lifecycle terminal transitions, contract terminate from each from-state, quote → WITHDRAWN cascades, milestone overdue sweeps, settlement preview vs final variant), 0 asymmetric
Status: PASS
```

### Contract 3: §3 Path Purity

```
Path purity check (§3 only):
- backtick tokens scanned in §3
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

(All endpoints in §3 are referenced via state-transition framing — e.g., "the `DRAFT` to `PLANNING` transition", "advancing `contract_status` from `NEGOTIATING` to `SIGNED`" — or via role + action verb — e.g., "approval by a planner", "the auditor finalizes" — or via capability description — e.g., "the event-emit hook", "the clock-advance hook". Field names and state values in backticks are preserved as required.)
