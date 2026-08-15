# Municipal Lien Search API — Product Requirements Document

## 1. Introduction

Before a residential closing can proceed, the title agent needs to know what the municipality is owed: unpaid utility balances, open code-enforcement violations with daily-accruing fines, expired or open permits, and recorded tax liens. If the property sits inside a homeowners' or condominium association, the agent additionally needs an estoppel letter — a statutorily regulated payoff statement whose response deadline, maximum fee, and validity period are fixed by the jurisdiction in force. A missed lien or a stale letter discovered after closing converts directly into a liability claim against the search provider. This product is the provider's operations platform: it accepts search orders from title agents, fans research out across the responsible municipal departments, orders and tracks estoppel letters against their statutory clocks, runs an independent payoff verification under segregation of duties, delivers a frozen result package, and adjudicates post-closing discrepancy claims against a capped liability figure.

The platform serves four operator populations with deliberately separated powers. Title agents own their orders and file claims but never touch research. Research analysts identify jurisdictions, record findings, and manage estoppel correspondence but never verify their own work. Quality-assurance reviewers verify payoff totals, resolve claims, and release deliveries but never file or research. A provider back office maintains the statutory reference data — jurisdictions, effective-dated statute windows, departments, and associations — and controls the logical clock that drives every deadline sweep in the system.

Two design commitments shape everything below. First, statutory arithmetic is exact: response deadlines, fee caps, validity windows, rush capacities, and liability caps are computed in whole cents and whole calendar days with pinned rounding and boundary semantics, because a closing attorney will hold the provider to the letter of each figure. Second, the order lifecycle is cyclic by design — verification can be rejected, estoppels expire, closing dates move, and confirmed claims reopen delivered work — so every forward step must also specify what its reversal unwinds.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the caller's role. A request missing either header, or carrying a malformed one, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not listed among an endpoint's authorized roles is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403). A role string naming anything other than the four recognized roles is not a known role at all: it is treated as a malformed header and rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400), as is a blank or whitespace-only `X-User-ID`.

The platform recognizes four operational roles, spelled exactly as follows: `TitleAgent`, `ResearchAnalyst`, `QAReviewer`, and `ProviderAdmin`. All four roles have opaque identities: when `X-User-Role` is `TitleAgent`, `ResearchAnalyst`, `QAReviewer`, or `ProviderAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it — as `title_agent_id` on a created order, as `research_completed_by_user_id` at submission for verification, as `completed_by_user_id` on a completed research task, as `payoff_verified_by_user_id` at payoff verification, as `filed_by_user_id` on a filed discrepancy, and as `resolved_by_user_id` at resolution — and compares it against those recorded values for ownership and segregation-of-duties checks, but it never matches an entity's `id`. A fifth designation, `Any`, is not a role a caller can present; it denotes that every authenticated role may use the read endpoints.

Ownership is enforced by identity comparison: the order-owning operations — updating an order, cancelling an order, filing a discrepancy against it, and acknowledging its delivery — require `X-User-ID` to equal the order's `title_agent_id`, and any other caller is rejected with `ERR_NOT_ORDER_OWNER` (HTTP 403).

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

List endpoints accept two optional query parameters, `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside `meta`. Items are always returned in `created_at` ascending order; because the logical clock can assign identical timestamps to several resources, ties are broken by insertion order — the order in which the server accepted the creates. Resource `id` values are never used for ordering. Out-of-range pagination values are clamped rather than rejected: a `limit` below 1 reads as 1 and above 100 as 100, a negative `offset` reads as 0, and a non-integer `limit` or `offset` falls back to its default.

### 2.4. The Logical Clock and Time-Driven Sweeps

The platform never consults wall-clock time. All temporal behavior is driven by a logical clock whose startup default is exactly 2026-08-01T00:00:00Z. A `ProviderAdmin` sets this clock through an administrative test-driving capability that accepts a `to_iso8601` instant — any ISO-8601 instant is accepted, including one behind the current reading, so the clock can move backward as well as forward, and a timestamp without an offset is read as UTC — and returns the `current_utc` reading. Setting the clock triggers the estoppel sweep: every estoppel order still awaiting its letter whose statutory due date has passed transitions from `ORDERED` to `OVERDUE`, and every received estoppel whose validity has lapsed on an order that is neither `DELIVERED` nor `CANCELLED` transitions from `RECEIVED` to `EXPIRED` with the cascades described in §3. All date comparisons in the system — service dates, closing dates, statute windows, statutory deadlines, validity horizons — are evaluated against this logical clock, and deadline arithmetic is expressed in whole calendar days on ISO dates; each such comparison is between whole calendar dates — the clock's date against the relevant ISO date — never between timestamps.

### 2.5. Common Resource Properties

Every resource carries a server-minted `id` formatted as a bare UUID with no type prefix, a `created_at` timestamp in ISO 8601 UTC with three fractional digits recording when the server accepted the create, an `updated_at` timestamp of the same format refreshed on every mutation, and a `version` integer that starts at 1 on creation and increments by exactly 1 on every accepted mutation of that resource — including mutations caused by system cascades such as task completion, estoppel receipt, or an expiry sweep touching the parent order. No entity in this domain is exempt: jurisdictions, statute windows, departments, associations, search orders, research tasks, estoppel orders, discrepancies, and deliveries all carry the full common set.

### 2.6. Monetary Representation and Rounding Discipline

All money is represented as integer cents; no response ever carries a fractional cent. Where a computation can produce a fractional intermediate — the daily accrual on a code-violation finding, and the extended-coverage fee — the fractional value is rounded half up to whole cents at a pinned point in the calculation: for findings, each finding's accrual is rounded to whole cents before any summation takes place, and only those rounded per-finding amounts are summed; for the coverage fee, the rate is applied to the provisional cap and the product is rounded half up once. Evaluation order is part of the contract wherever a later step consumes an earlier step's result, most critically the liability-cap algorithm in §3.6, whose five steps must run in their stated sequence.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only those two accept a version field.

Updating a search order requires the request to carry `expected_search_order_version` holding the caller's last observed `version` of that order. If the order's current `version` has advanced since — because another accepted write, including a cascaded mutation from task completion, estoppel receipt, or an expiry sweep, moved it forward — the update is rejected with `ERR_STALE_VERSION` (HTTP 412), since the caller's `closing_date` or `association_id` edit rests on a stale view. Exactly these child events advance the parent order's `version`: research-task completion, estoppel receipt, an expiry sweep expiring one of the order's estoppels, discrepancy filing, discrepancy resolution, and delivery release; findings writes, mark-unreachable, estoppel placement and cancellation, delivery creation and acknowledgement, and discrepancy start-review leave the order's `version` unchanged.

Recording findings on a research task likewise requires `expected_research_task_version` matching the task's current `version`. Because findings use overwrite semantics, a write based on an older version would silently discard an update it never saw, so the mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) and the writer must re-read the task and resubmit. On both guarded endpoints a missing or non-integer version field is `ERR_INVALID_REQUEST` (HTTP 400). No other endpoint takes a version field.

### 2.8. Validation Pipeline and Check Ordering

Inbound requests pass through an ordered pipeline of validation categories, and the ordering matters because a request that would fail several checks must surface the earliest one. The pipeline runs in this sequence: first, the presence and well-formedness of the user-context headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); second, whether the caller's role is authorized for the endpoint (`ERR_FORBIDDEN_FOR_ROLE`); third, whether every referenced resource — path identifiers and body references alike, spanning jurisdictions, statutes, departments, associations, orders, tasks, estoppels, discrepancies, and deliveries — actually exists (`ERR_NOT_FOUND`); fourth, whether the target resource sits in a state that permits the requested transition, including the blanket refusal of any transition out of a terminal state and the deliverability gate on delivery (`ERR_INVALID_STATE_TRANSITION` or `ERR_ORDER_NOT_DELIVERABLE` as applicable); fifth, ownership (`ERR_NOT_ORDER_OWNER`); sixth, segregation of duties (`ERR_SOD_VIOLATION`); seventh, referential business rules tying associations to jurisdictions and statutes to the clock date (`ERR_ASSOCIATION_JURISDICTION_MISMATCH`, `ERR_NO_STATUTE_IN_FORCE`, `ERR_FEE_EXCEEDS_STATUTORY_CAP`); eighth, temporal validity (`ERR_SERVICE_DATE_PAST`, `ERR_CLOSING_DATE_PASSED`, `ERR_STATUTE_WINDOW_OVERLAP`, `ERR_ESTOPPEL_STALE_FOR_CLOSING`); ninth, structural business constraints such as rush support, rush capacity, duplicate service windows, outstanding tasks, and estoppel currency; and tenth, fiscal checks on payoff totals and claim amounts (`ERR_PAYOFF_MISMATCH`, `ERR_CLAIM_AMOUNT_INVALID`). Two further checks occupy fixed positions relative to this pipeline. Request body-shape validation — missing required fields, wrong JSON types, unknown enum values, all surfacing as `ERR_INVALID_REQUEST` (HTTP 400) — runs immediately after the role check on creation endpoints, before the existence checks on body-referenced resources; on endpoints addressed at a path resource it runs after that path resource's own existence and state guard, with the existence of body-referenced resources checked as part of it, and jurisdiction identification is the lone exception, validating the body's `jurisdiction_id` before the order's state guard. The optimistic-concurrency check (`ERR_STALE_VERSION`) runs after the ownership and segregation-of-duties categories and before the referential business-rule category. A request body that is absent or unparseable JSON is treated as an empty object, while a JSON body that is not an object is itself `ERR_INVALID_REQUEST`.

### 2.9. Statutory Reference Data as a Pinned Point-in-Time Contract

A jurisdiction's statute set is a sequence of effective-dated windows. Each window carries an inclusive `effective_from` and an exclusive `effective_to`, so coverage is half-open: a window covers a date when the date is on or after `effective_from` and strictly before `effective_to`, and a null `effective_to` makes the window open-ended. Windows of one jurisdiction must never overlap; a new window whose `effective_from` equals an existing window's `effective_to` is adjacent, not overlapping, and is allowed, while any true overlap is rejected with `ERR_STATUTE_WINDOW_OVERLAP`. The statute carries three statutory parameters — `estoppel_response_days`, `estoppel_fee_cap_cents`, and `estoppel_validity_days` — and a search order pins whichever window covers the clock date at the moment its jurisdiction is identified, keeping that statute for the life of the order regardless of later legislative changes. A fee cap of 0 means the association must issue its letter free of charge.

## 3. Business Logic & Workflows

### 3.1. Building the Jurisdictional Reference Book

Before any order can be worked, the provider's back office assembles the reference book. A `ProviderAdmin` creates each jurisdiction with a `code` (recorded as supplied — uniqueness is a data-entry convention and is not server-enforced), a display `name`, a `state_code` (accepted as any non-empty string; the two-letter convention is not validated), and an optional `rush_daily_capacity` governing how many rush orders the jurisdiction accepts per service date; the capacity defaults to 5 when omitted. A jurisdiction is born `ACTIVE`, and only an `ACTIVE` jurisdiction accepts jurisdiction identification; deactivation flips its `status` to `INACTIVE` and blocks new identifications without disturbing orders already in flight. Deactivation is idempotent: deactivating an already-`INACTIVE` jurisdiction succeeds with HTTP 200 and no further mutation.

Statute windows are then registered against the jurisdiction by supplying the `jurisdiction_id`, the `effective_from` and `effective_to` dates, and the three statutory parameters described in §2.9. The half-open overlap rule is enforced at registration against that jurisdiction's existing windows.

Each jurisdiction's municipal departments are registered with a `dept_type` drawn from exactly four values — `UTILITY`, `CODE_ENFORCEMENT`, `PERMIT`, and `TAX_COLLECTOR` — together with a `name` and a base `research_fee_cents` charged when a task completes. An optional `rush_surcharge_cents`, defaulting to 0, adds a per-task premium on rush orders, and `supports_rush`, defaulting to true, declares whether the department accepts rush turnaround. Only one `ACTIVE` department of each `dept_type` may exist per jurisdiction; a duplicate active type is refused with `ERR_DUPLICATE_DEPARTMENT_TYPE`. Departments are born `ACTIVE`; deactivating one flips its `status` to `INACTIVE`, and future jurisdiction identifications simply skip it when spawning research tasks. Deactivating an already-`INACTIVE` department likewise succeeds with HTTP 200 and no further mutation.

Associations are registered within a jurisdiction by supplying the `jurisdiction_id`, the association `name`, its `management_company`, the `estoppel_fee_cents` it quotes for a letter, and its own `estoppel_validity_days`. At registration, a statute window must cover the current clock date for that jurisdiction — when none does, registration fails with `ERR_NO_STATUTE_IN_FORCE` — and the quoted fee is checked against the fee cap of that covering window; a quote above the in-force cap is rejected with `ERR_FEE_EXCEEDS_STATUTORY_CAP`. Every monetary amount and day count registered in this section — `rush_daily_capacity`, the three statutory parameters, `research_fee_cents`, `rush_surcharge_cents`, `estoppel_fee_cents`, and `estoppel_validity_days` — must be a non-negative integer; anything else is `ERR_INVALID_REQUEST`.

### 3.2. Ordering a Search: Intake, Rush Admission, and Parcel Exclusivity

A `TitleAgent` opens a search order by supplying the `property_address`, the assessor `parcel_number`, the scheduled `closing_date`, the `order_class` (`STANDARD` or `RUSH`), and optionally an `association_id` when the property sits inside an association, plus an `extended_coverage` flag, defaulting to false, that purchases extended liability protection. The order is born in `INTAKE`, and its `title_agent_id` is copied from the caller's `X-User-ID`; the `jurisdiction_id` and `statute_id` remain null until jurisdiction identification.

Rush orders carry extra admission rules. A `RUSH` order must declare its `service_date` — the date its research slot is reserved — and a candidate `jurisdiction_id` at creation, both of which are required and whose absence is `ERR_INVALID_REQUEST`; a `STANDARD` order leaves both null, and any `service_date` or `jurisdiction_id` supplied on a `STANDARD` creation is ignored. The declared jurisdiction is persisted as `rush_candidate_jurisdiction_id` and drives all capacity accounting. The service date must not be before the current clock date, or creation fails with `ERR_SERVICE_DATE_PAST`. Every `ACTIVE` department of the candidate jurisdiction must support rush, or creation fails with `ERR_RUSH_NOT_SUPPORTED`. Finally, the jurisdiction's daily rush capacity is enforced by counting existing non-`CANCELLED` rush orders whose `rush_candidate_jurisdiction_id` equals the requested jurisdiction and whose `service_date` equals the requested date: if that occupant count already equals or exceeds the jurisdiction's `rush_daily_capacity`, creation is rejected with `ERR_RUSH_CAPACITY_FULL`, while a count exactly one below capacity is still accepted.

Regardless of class, every new order faces the parcel exclusivity rule. Each existing non-`CANCELLED` order for the same `parcel_number` occupies a service window running from its creation date through its `closing_date`, with both ends inclusive. A new order conflicts — and is rejected with `ERR_DUPLICATE_ACTIVE_SEARCH` — when the existing order's creation date falls on or before the requested `closing_date` and the current clock date falls on or before the existing order's `closing_date`. Because the interval is closed at both ends, a new order created exactly on the existing order's closing date still conflicts; adjacency is not an escape. Cancelling the existing order frees the parcel immediately. A `closing_date` earlier than the current clock date is rejected with `ERR_CLOSING_DATE_PASSED`.

### 3.3. Identifying the Jurisdiction and Fanning Out the Work

Jurisdiction identification is the pivot from intake to research. A `ResearchAnalyst` identifies the governing jurisdiction for an order in `INTAKE`, which must reference an existing, `ACTIVE` jurisdiction — a missing one surfaces as `ERR_NOT_FOUND`, an inactive one as `ERR_INVALID_STATE_TRANSITION`. A statute window must cover the current clock date for that jurisdiction; if none does, the call fails with `ERR_NO_STATUTE_IN_FORCE`. When the order carries an `association_id`, the association must belong to the identified jurisdiction, failing with `ERR_ASSOCIATION_JURISDICTION_MISMATCH` otherwise. For a rush order, the identified jurisdiction must equal the `rush_candidate_jurisdiction_id` declared at creation; any other jurisdiction is rejected with `ERR_INVALID_REQUEST`, because the capacity reservation was accounted against the candidate. These rejections surface in a fixed sequence: the order's `INTAKE` state first, then rush-candidate equality, then the jurisdiction's `ACTIVE` status, then statute coverage, then association belonging.

A successful identification moves the order from `INTAKE` to `RESEARCH_IN_PROGRESS`, writes the `jurisdiction_id`, pins the covering statute into `statute_id` for the life of the order, and advances the order's `version` by 1. It then spawns one research task in `PENDING` for each `ACTIVE` department of the jurisdiction, created in department `created_at` ascending order so the task list is deterministic; each task snapshots the department's current `research_fee_cents` into `fee_base_cents` and `rush_surcharge_cents` into `fee_rush_surcharge_cents`, copies the `dept_type`, and records its `search_order_id` and `department_id`. When an association is attached, an estoppel order is also spawned in `DRAFT` against that association.

### 3.4. Working the Research: Findings, Balances, and Task Completion

Analysts record findings on a task through a single write that also serves as the task's start signal. The first call against a `PENDING` task auto-starts it, moving it to `IN_PROGRESS`; the same call against an `UNABLE_TO_REACH` task retries it, clearing the recorded `unreachable_reason` and returning it to `IN_PROGRESS`; and a call against an `IN_PROGRESS` task overwrites the stored `findings` wholesale. Every such write carries the OCC guard `expected_research_task_version` described in §2.7, advances the task's `version`, and sets `findings_recorded` to true.

Each finding is an entry in the `findings` array with a `finding_kind` of `UNPAID_UTILITY`, `CODE_VIOLATION`, `OPEN_PERMIT`, or `TAX_LIEN`, an `amount_cents`, and optionally a `daily_accrual_cents` — which may itself be fractional, such as 133.5 — a `days_outstanding` count, and a free-text `description`. The task's `unpaid_balance_cents` is recomputed on every findings write: for each finding whose `finding_kind` is `CODE_VIOLATION` and that carries both a daily accrual and a day count, the finding's effective amount is its `amount_cents` plus the product of `daily_accrual_cents` and `days_outstanding` rounded half up to whole cents; every other finding contributes its `amount_cents` unchanged. The per-finding effective amounts are rounded first and only then summed into `unpaid_balance_cents`. The `open_violation_count` is the count of findings whose kind is `CODE_VIOLATION`. No sign constraint is enforced on `amount_cents`, `daily_accrual_cents`, or `days_outstanding`, and an empty `findings` array is accepted, yielding a zero `unpaid_balance_cents` and a zero `open_violation_count`.

Completion turns findings into money. Completing a task — allowed only once findings have been recorded — moves it from `IN_PROGRESS` to `COMPLETED`, records the caller in `completed_by_user_id`, and fixes `fee_charged_cents` as the snapshotted `fee_base_cents` plus, when the owning order is `RUSH`, the snapshotted `fee_rush_surcharge_cents`; before completion, and again after any reopen, `fee_charged_cents` reads zero. The order's `total_fees_cents` grows by that charge and its `total_payoff_cents` grows by the task's `unpaid_balance_cents`. A task that cannot reach its department can instead be moved to `UNABLE_TO_REACH` from either `PENDING` or `IN_PROGRESS` with a `reason` stored as `unreachable_reason`; such a task contributes nothing to order totals until it is retried and completed.

The order's payoff total is defined precisely: `total_payoff_cents` is the sum of `unpaid_balance_cents` over the order's `COMPLETED` research tasks plus the sum of `payoff_amount_cents` over its `RECEIVED` estoppel orders — tasks in any other state and estoppels in any other state contribute zero. Likewise `total_fees_cents` is the sum of `fee_charged_cents` over `COMPLETED` tasks plus the sum of `lifetime_fees_cents` over estoppels in `RECEIVED` or `EXPIRED`; once charged, fees are never refunded, even by cancellation.

### 3.5. The Estoppel Letter: Statutory Deadlines, Fee Forfeiture, Expiry, and Renewal

When the property lies in an association, a `DRAFT` estoppel order waits for placement. Placing it is a `ResearchAnalyst` action carrying the association's quoted `fee_quoted_cents`, which must be an integer strictly greater than zero and no greater than the fee cap of the order's pinned statute; a quote that is missing, non-integral, or not strictly greater than zero is rejected with `ERR_INVALID_REQUEST`, while a positive quote above the cap — including any positive quote when the pinned cap is 0, since the statute then requires a free letter — is rejected with `ERR_QUOTE_EXCEEDS_STATUTORY_CAP`. Placement moves the estoppel from `DRAFT` to `ORDERED`, stamps `ordered_at` with the clock, and computes `statutory_due_at` as the ordered date plus the statute's `estoppel_response_days` calendar days, fixed at 23:59:59.000Z on the resulting date.

Receipt closes the statutory loop. When the letter arrives while the estoppel is `ORDERED`, receipt is on time: `received_at` is stamped, `late_delivery` is set false, `current_fee_cents` becomes the quoted fee — clamped as the lesser of `fee_quoted_cents` and the pinned cap, though placement already guarantees the quote is within cap — and `lifetime_fees_cents` grows by that amount. When the clock sweep has already moved the estoppel to `OVERDUE` because the clock date passed the statutory due date, receipt is late: `late_delivery` is set true, `current_fee_cents` is zero by statutory fee forfeiture, and `lifetime_fees_cents` is unchanged. In both cases the caller supplies the letter's `payoff_amount_cents`, which must be zero or greater or the call fails with `ERR_INVALID_REQUEST`; `valid_through` is computed as the received date plus the association's `estoppel_validity_days` calendar days; and the order's `total_payoff_cents` grows by `payoff_amount_cents` while `total_fees_cents` grows by `current_fee_cents` — so an identical quote and payoff arriving on time versus late produce different fee totals. An estoppel is current for closing exactly when the order's `closing_date` is on or before `valid_through`; the boundary day itself counts as valid. An estoppel is late exactly when its received date is after its statutory due date.

Letters age out. Whenever the logical clock is set past a received estoppel's `valid_through` and the owning order is neither `DELIVERED` nor `CANCELLED`, the sweep moves the estoppel from `RECEIVED` to `EXPIRED` and subtracts its `payoff_amount_cents` from the order's `total_payoff_cents` — the lifetime fees, once earned, stay in `total_fees_cents`. If the order was sitting in `VERIFICATION` or `READY_FOR_DELIVERY` at that moment, it reverts to `RESEARCH_IN_PROGRESS` with its payoff verification cleared, and any `READY` delivery of the order is voided. An expired letter can be renewed by placing it again: the same cap check applies, `renewal_count` increments by 1, `ordered_at` and `statutory_due_at` are recomputed, the previous receipt's `received_at`, `payoff_amount_cents`, `valid_through`, and `late_delivery` are cleared, and `current_fee_cents` returns to zero until the next receipt. A `DRAFT`, `ORDERED`, or `OVERDUE` estoppel can also be cancelled outright — for instance when the association declines — with no fee impact since nothing was ever received; cancellation also arrives by cascade when the order is cancelled or when an update clears or changes the order's `association_id`.

### 3.6. Verification, Delivery, and the Frozen Liability Snapshot

Once every research task of an order is `COMPLETED` or `UNABLE_TO_REACH` — any task still `PENDING` or `IN_PROGRESS` blocks submission with `ERR_TASKS_OUTSTANDING` — and every estoppel order is `RECEIVED` (anything else blocks with `ERR_ESTOPPEL_NOT_CURRENT`) with a `valid_through` on or after the `closing_date` (a stale letter blocks with `ERR_ESTOPPEL_STALE_FOR_CLOSING`), a `ResearchAnalyst` submits the order for verification, moving it to `VERIFICATION` and stamping `research_completed_by_user_id` with the caller's identity.

Verification is performed by a `QAReviewer` who independently computes the payoff and submits it as `verified_payoff_total_cents`. If that figure differs from the order's computed `total_payoff_cents`, verification fails with `ERR_PAYOFF_MISMATCH`. Segregation of duties is enforced two ways: the verifier's identity must differ from `research_completed_by_user_id` and from the `completed_by_user_id` of every `COMPLETED` research task on the order, with a breach rejected as `ERR_SOD_VIOLATION`. Successful verification moves the order to `READY_FOR_DELIVERY`, records `payoff_verified_by_user_id`, and stamps `payoff_verified_at`. A reviewer who is not satisfied instead rejects the verification with a `reason`, returning the order to `RESEARCH_IN_PROGRESS` and clearing both verification fields.

With the order `READY_FOR_DELIVERY`, a `QAReviewer` creates a delivery for it; the creation is refused with `ERR_ORDER_NOT_DELIVERABLE` when the order is in any other state and with `ERR_DELIVERY_ALREADY_PENDING` when a `READY` delivery already exists for the order. The new delivery is born `READY`. Releasing it to the title agent requires the order still to be `READY_FOR_DELIVERY` (again `ERR_ORDER_NOT_DELIVERABLE` otherwise) and the `closing_date` to be on or after the current clock date (`ERR_CLOSING_DATE_PASSED` otherwise). At the moment of release the delivery freezes its evidence: `snapshot_payoff_cents` and `snapshot_fees_cents` copy the order's totals, the liability-cap algorithm runs and its results are frozen into `coverage_fee_cents` and `liability_cap_cents`, `delivered_at` is stamped, `delivered_to_agent_id` copies the order's `title_agent_id`, and the order itself moves from `READY_FOR_DELIVERY` to `DELIVERED`. The owning `TitleAgent` then acknowledges receipt, moving the delivery from `DELIVERED` to `ACKNOWLEDGED`; anyone else is refused with `ERR_NOT_ORDER_OWNER`.

The liability cap is a five-step computation whose evaluation order is pinned because the coverage fee depends on the provisional cap while the final cap depends on totals that include the coverage fee. Step one takes the order's current `total_fees_cents` as the base. Step two derives the provisional cap: ten times the base, clamped below by a floor of 25000 cents and above by a ceiling of 100000 cents — that is, the larger of the floor and the smaller of ten-times-base and the ceiling. Step three computes the extended-coverage fee: when the order's `extended_coverage` is true, the fee is ten percent of the provisional cap rounded half up to whole cents; when false, it is zero. Step four adds the coverage fee to the base. Step five derives the final cap by applying the identical clamp to ten times that coverage-inclusive sum: the larger of 25000 cents and the smaller of ten-times-the-sum and 100000 cents. On release, the resulting coverage fee and final cap are frozen onto the delivery and never recomputed. The order-summary read, by contrast, always re-runs the same five steps over current totals — never reusing a frozen snapshot — so fees accruing after delivery can raise the projection, which it reports as `projected_coverage_fee_cents` and `projected_liability_cap_cents` alongside `total_payoff_cents`, `total_fees_cents`, `pending_claims_cents`, `total_liability_cents`, a `task_counts` breakdown keyed by all five task statuses (`PENDING`, `IN_PROGRESS`, `COMPLETED`, `UNABLE_TO_REACH`, `CANCELLED`), the `estoppel_count` counting every estoppel order of the order whatever its status, the `open_discrepancy_count` counting claims in `OPEN` or `UNDER_REVIEW`, and the `latest_delivery_status` — the status of the order's most recently created delivery, or null when the order has none.

### 3.7. Mid-Flight Corrections: Updating and Cancelling an Order

While an order is in `INTAKE`, `RESEARCH_IN_PROGRESS`, `VERIFICATION`, or `READY_FOR_DELIVERY`, its owning `TitleAgent` may update the `closing_date`, the `association_id`, or both, always under the `expected_search_order_version` OCC guard of §2.7; a caller other than the owner is refused with `ERR_NOT_ORDER_OWNER`. The body must name at least one of the two fields, and `closing_date` must not be null; violations are `ERR_INVALID_REQUEST`. The update advances the order's `version` by exactly 1. Moving the `closing_date` re-evaluates estoppel staleness immediately: any `RECEIVED` estoppel whose `valid_through` now falls before the new closing date pulls an order in `VERIFICATION` or `READY_FOR_DELIVERY` back to `RESEARCH_IN_PROGRESS` with its payoff verification cleared, and a new date earlier than the clock date is refused with `ERR_CLOSING_DATE_PASSED`. Changing the `association_id` cancels every `DRAFT`, `ORDERED`, or `OVERDUE` estoppel of the old association and spawns a fresh `DRAFT` estoppel for the new one — though only once the order has an identified jurisdiction: while the order is still in `INTAKE`, or when the association is merely cleared to null, no new draft is spawned, and a draft for an association recorded during `INTAKE` is spawned at identification; naming the association already on the order is a no-op that cancels and spawns nothing. The change is rejected with `ERR_INVALID_STATE_TRANSITION` when any estoppel has already been `RECEIVED`, and with `ERR_ASSOCIATION_JURISDICTION_MISMATCH` when the new association belongs to a different jurisdiction than the order — a check that applies only once the order has an identified jurisdiction, since beforehand the mismatch surfaces at identification.

Cancellation unwinds gracefully. The owning `TitleAgent` may cancel an order that has not been delivered, from any of `INTAKE`, `RESEARCH_IN_PROGRESS`, `VERIFICATION`, or `READY_FOR_DELIVERY`. Cancelling from `INTAKE` simply resolves the claims tail described below. Cancelling from a research-stage state additionally cascades: research tasks in `PENDING`, `IN_PROGRESS`, or `UNABLE_TO_REACH` move to `CANCELLED`, while `COMPLETED` tasks keep their fees; estoppels in `DRAFT`, `ORDERED`, or `OVERDUE` move to `CANCELLED`, while `RECEIVED` and `EXPIRED` estoppels keep their `lifetime_fees_cents` in the order's totals; and cancelling from `READY_FOR_DELIVERY` also voids any `READY` delivery. Across all cancellation paths, every `OPEN` or `UNDER_REVIEW` discrepancy of the order is force-resolved with `resolution_outcome` set to `VOID_ORDER_CANCELLED`, and the order's `pending_claims_cents` is decremented by each released claim. A force-resolution is system-driven and records no `resolved_by_user_id`; the field stays null. `CANCELLED` is terminal: no further transition out of it is permitted, and the same terminal lockdown applies to `CANCELLED` tasks and estoppels and to deliveries that have reached `ACKNOWLEDGED`, `SUPERSEDED`, or `VOIDED`.

### 3.8. Discrepancy Claims and Liability Accounting

When the delivered package — or work still in flight — is disputed, the owning `TitleAgent` files a discrepancy against the order, naming the `search_order_id`, the polymorphic `subject_type` (`SEARCH_ORDER`, `RESEARCH_TASK`, or `ESTOPPEL_ORDER`) with the corresponding `subject_id`, a `discrepancy_type` of `MISSED_ITEM`, `BALANCE_MISMATCH`, `PAYOFF_MISMATCH`, or `STALE_ESTOPPEL`, the `claimed_amount_cents`, and a free-text `description`. The subject must belong to the named order — a task or estoppel from another order, or a mismatched order reference, fails with `ERR_SUBJECT_NOT_IN_ORDER`. The claim amount must be strictly greater than zero and no greater than 25000000 cents; anything outside that band fails with `ERR_CLAIM_AMOUNT_INVALID`. A `MISSED_ITEM` claim is only meaningful after delivery: filing one before the order is delivered, or on a `CANCELLED` order, is refused with `ERR_DISCREPANCY_NOT_APPLICABLE`. The discrepancy is born `OPEN`, its `filed_by_user_id` records the caller, `confirmed_liability_cents` starts at zero, and `post_delivery` is computed true exactly when the order stood `DELIVERED` at filing time. Filing immediately adds `claimed_amount_cents` to the order's `pending_claims_cents`, the running exposure across the order's `OPEN` and `UNDER_REVIEW` claims.

A `QAReviewer` picks the claim up by starting review, moving it from `OPEN` to `UNDER_REVIEW`, and later resolves it — moving it to `RESOLVED`, its terminal state — with a `resolution_outcome` of `CONFIRMED_CORRECTION`, `REJECTED_INVALID`, or `VOID_ORDER_CANCELLED`. Segregation of duties applies here as well: the resolver's identity must differ from `filed_by_user_id`, failing with `ERR_SOD_VIOLATION`. Resolving a `MISSED_ITEM` as `CONFIRMED_CORRECTION` requires a `confirmed_amount_cents` greater than zero, failing with `ERR_INVALID_REQUEST` otherwise. Every resolution records `resolved_by_user_id`, subtracts the `claimed_amount_cents` from `pending_claims_cents`, records a supplied `confirmed_amount_cents` whatever the outcome, and leaves `confirmed_liability_cents` at zero unless a cascade below sets it.

Confirmed corrections unwind the pipeline in three distinct ways, applied together when several match. For a confirmed post-delivery `MISSED_ITEM`, `confirmed_liability_cents` is set to the lesser of `confirmed_amount_cents` and the `liability_cap_cents` of the order's most recently created delivery in `DELIVERED` or `ACKNOWLEDGED` status (a cap of zero when no delivery stands in either status) — so the same claim amount yields a cap-limited figure against a delivered cap — the order's `total_liability_cents` grows by that amount, and a `DELIVERED` order cascades back to `RESEARCH_IN_PROGRESS` with its payoff verification cleared and its `DELIVERED` or `ACKNOWLEDGED` deliveries moved to `SUPERSEDED`. For a confirmed correction whose subject is a research task, the subject task reopens from `COMPLETED` to `IN_PROGRESS`: the order's `total_fees_cents` decreases by the task's `fee_charged_cents`, which itself resets to zero, the order's `total_payoff_cents` decreases by the task's `unpaid_balance_cents`, and `completed_by_user_id` is cleared. And for a confirmed correction filed before delivery while the order sits in `VERIFICATION` or `READY_FOR_DELIVERY`, the order reverts to `RESEARCH_IN_PROGRESS` with verification cleared and any `READY` deliveries voided. Claims resolved as `REJECTED_INVALID` simply release their pending amount with no further cascade, as do the force-resolved `VOID_ORDER_CANCELLED` outcomes produced by order cancellation. Across the order, `total_liability_cents` is the running sum of `confirmed_liability_cents` over its `RESOLVED` discrepancies.

## 4. Endpoint Definitions

All endpoints live under the API root. Creating a new resource returns HTTP 201 with the created resource; operations that modify an existing resource, and all reads, return HTTP 200. Error responses carry the status codes catalogued in §5. Requests to unknown paths — and to known paths with an unsupported method — are answered with `ERR_NOT_FOUND` (HTTP 404) in the standard error envelope.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Set the logical clock; triggers the estoppel overdue/expiry sweep | ProviderAdmin |
| POST | /jurisdictions | Create a jurisdiction | ProviderAdmin |
| GET | /jurisdictions/{id} | Get a jurisdiction | TitleAgent, ResearchAnalyst, QAReviewer, ProviderAdmin |
| GET | /jurisdictions/{id}/search-orders | List search orders identified to this jurisdiction | TitleAgent, ResearchAnalyst, QAReviewer, ProviderAdmin |
| POST | /jurisdictions/{id}/deactivate | Deactivate a jurisdiction | ProviderAdmin |
| POST | /statutes | Create an effective-dated statute window | ProviderAdmin |
| GET | /statutes/{id} | Get a statute | TitleAgent, ResearchAnalyst, QAReviewer, ProviderAdmin |
| GET | /jurisdictions/{id}/statutes | List statutes of a jurisdiction | TitleAgent, ResearchAnalyst, QAReviewer, ProviderAdmin |
| GET | /statutes/{id}/search-orders | List search orders that pinned this statute | TitleAgent, ResearchAnalyst, QAReviewer, ProviderAdmin |
| POST | /departments | Create a department for a jurisdiction | ProviderAdmin |
| GET | /departments/{id} | Get a department | TitleAgent, ResearchAnalyst, QAReviewer, ProviderAdmin |
| GET | /jurisdictions/{id}/departments | List departments of a jurisdiction | TitleAgent, ResearchAnalyst, QAReviewer, ProviderAdmin |
| GET | /departments/{id}/research-tasks | List research tasks spawned from this department | TitleAgent, ResearchAnalyst, QAReviewer, ProviderAdmin |
| POST | /departments/{id}/deactivate | Deactivate a department | ProviderAdmin |
| POST | /associations | Register an association within a jurisdiction | ProviderAdmin |
| GET | /associations/{id} | Get an association | TitleAgent, ResearchAnalyst, QAReviewer, ProviderAdmin |
| GET | /jurisdictions/{id}/associations | List associations of a jurisdiction | TitleAgent, ResearchAnalyst, QAReviewer, ProviderAdmin |
| GET | /associations/{id}/search-orders | List search orders referencing this association | TitleAgent, ResearchAnalyst, QAReviewer, ProviderAdmin |
| GET | /associations/{id}/estoppel-orders | List estoppel orders placed with this association | TitleAgent, ResearchAnalyst, QAReviewer, ProviderAdmin |
| POST | /search-orders | Create a search order in INTAKE | TitleAgent |
| GET | /search-orders/{id} | Get a search order | TitleAgent, ResearchAnalyst, QAReviewer, ProviderAdmin |
| PATCH | /search-orders/{id} | Update closing date and/or association (OCC-guarded, owner only) | TitleAgent |
| POST | /search-orders/{id}/identify-jurisdiction | Identify jurisdiction, pin statute, spawn tasks and estoppel draft | ResearchAnalyst |
| POST | /search-orders/{id}/cancel | Cancel a non-delivered order with cascades (owner only) | TitleAgent |
| POST | /search-orders/{id}/submit-for-verification | Move order to VERIFICATION | ResearchAnalyst |
| POST | /search-orders/{id}/verify-payoff | Independently verify the payoff total (SoD-enforced) | QAReviewer |
| POST | /search-orders/{id}/reject-verification | Reject verification; return order to research | QAReviewer |
| GET | /search-orders/{id}/summary | Computed totals, liability-cap projection, and status breakdowns | TitleAgent, ResearchAnalyst, QAReviewer, ProviderAdmin |
| GET | /search-orders/{id}/research-tasks | List research tasks of an order | TitleAgent, ResearchAnalyst, QAReviewer, ProviderAdmin |
| GET | /research-tasks/{id} | Get a research task | TitleAgent, ResearchAnalyst, QAReviewer, ProviderAdmin |
| POST | /research-tasks/{id}/record-findings | Record or overwrite findings (auto-starts, retries; OCC-guarded) | ResearchAnalyst |
| POST | /research-tasks/{id}/complete | Complete a task once findings are recorded | ResearchAnalyst |
| POST | /research-tasks/{id}/mark-unreachable | Mark a task unable to reach with a reason | ResearchAnalyst |
| GET | /search-orders/{id}/estoppel-orders | List estoppel orders of an order | TitleAgent, ResearchAnalyst, QAReviewer, ProviderAdmin |
| GET | /estoppel-orders/{id} | Get an estoppel order | TitleAgent, ResearchAnalyst, QAReviewer, ProviderAdmin |
| POST | /estoppel-orders/{id}/place | Place the estoppel with the association (initial or renewal) | ResearchAnalyst |
| POST | /estoppel-orders/{id}/receive | Record receipt of the letter (on-time or late with fee forfeiture) | ResearchAnalyst |
| POST | /estoppel-orders/{id}/cancel | Cancel a draft/ordered/overdue estoppel | ResearchAnalyst |
| POST | /discrepancies | File a discrepancy against an order (owner only) | TitleAgent |
| GET | /discrepancies/{id} | Get a discrepancy | TitleAgent, ResearchAnalyst, QAReviewer, ProviderAdmin |
| GET | /search-orders/{id}/discrepancies | List discrepancies of an order | TitleAgent, ResearchAnalyst, QAReviewer, ProviderAdmin |
| POST | /discrepancies/{id}/start-review | Open QA review of a discrepancy | QAReviewer |
| POST | /discrepancies/{id}/resolve | Resolve a discrepancy (SoD-enforced; correction cascades) | QAReviewer |
| POST | /deliveries | Create a READY delivery for a deliverable order | QAReviewer |
| GET | /deliveries/{id} | Get a delivery | TitleAgent, ResearchAnalyst, QAReviewer, ProviderAdmin |
| GET | /search-orders/{id}/deliveries | List deliveries of an order | TitleAgent, ResearchAnalyst, QAReviewer, ProviderAdmin |
| POST | /deliveries/{id}/deliver | Release the result package; freeze the liability snapshot | QAReviewer |
| POST | /deliveries/{id}/acknowledge | Acknowledge receipt of the delivery (owner only) | TitleAgent |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_FOR_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE_TRANSITION | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_NOT_ORDER_OWNER | 403 |
| ERR_SOD_VIOLATION | 403 |
| ERR_ASSOCIATION_JURISDICTION_MISMATCH | 422 |
| ERR_NO_STATUTE_IN_FORCE | 422 |
| ERR_FEE_EXCEEDS_STATUTORY_CAP | 422 |
| ERR_STATUTE_WINDOW_OVERLAP | 422 |
| ERR_SERVICE_DATE_PAST | 422 |
| ERR_CLOSING_DATE_PASSED | 422 |
| ERR_RUSH_NOT_SUPPORTED | 409 |
| ERR_RUSH_CAPACITY_FULL | 409 |
| ERR_DUPLICATE_ACTIVE_SEARCH | 409 |
| ERR_DUPLICATE_DEPARTMENT_TYPE | 409 |
| ERR_TASKS_OUTSTANDING | 409 |
| ERR_ESTOPPEL_NOT_CURRENT | 409 |
| ERR_ESTOPPEL_STALE_FOR_CLOSING | 422 |
| ERR_QUOTE_EXCEEDS_STATUTORY_CAP | 422 |
| ERR_SUBJECT_NOT_IN_ORDER | 409 |
| ERR_DISCREPANCY_NOT_APPLICABLE | 409 |
| ERR_CLAIM_AMOUNT_INVALID | 422 |
| ERR_PAYOFF_MISMATCH | 409 |
| ERR_ORDER_NOT_DELIVERABLE | 409 |
| ERR_DELIVERY_ALREADY_PENDING | 409 |
