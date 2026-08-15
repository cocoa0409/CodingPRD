# Transaction Coordinator Service API — Product Requirements Document

## 1. Introduction

Independent transaction coordinators occupy the unglamorous middle of every residential real-estate deal. Once a purchase contract is signed or a listing agreement is executed, someone has to track which disclosures are due in which state, chase the buyer's agent for an inspection report, recompute contingency deadlines when an amendment moves the effective date, keep the title company and the lender aligned until clear-to-close, and produce a clean, auditable file that a broker, an auditor, or a court can rely on months later. That work is currently done in spreadsheets and inbox folders, and it fails in predictable ways: a financing contingency expires unobserved, a mandatory milestone is silently skipped, an amendment is signed by only one side but treated as effective, or the invoice that goes out at closing does not reflect the amendment fees the coordinator is contractually owed.

This document specifies the Transaction Coordinator Service API, a multi-tenant platform that models the contract-to-close lifecycle as a set of explicit state machines with enforced transitions. A coordinator registers a roster of agents, publishes (through a platform administrator) state- and contract-type-specific milestone checklist templates, opens a transaction file, activates it against a pinned template version, tracks documents and deadlines, routes amendments for signature, coordinates title and lender confirmation, and finally closes, invoices, and archives the file. Time itself is a first-class input to the system: deadline expiries, reminder dispatches, milestone overdue transitions, and communication escalations are all driven by an administrator-controlled logical clock rather than by the wall clock, so that behavior is deterministic and testable.

The specification below is organized in four parts. Section 2 fixes the system-wide contracts every endpoint shares — authentication headers, response envelopes, pagination, resource identity, monetary precision, concurrency control, and validation ordering. Section 3 walks the business workflows in narrative form, scattering the concrete field names, thresholds, and formulas into the context where each rule actually fires. Section 4 is a compact endpoint index, and Section 5 is the error-code catalogue. Readers implementing against this document should treat Section 3 as the source of behavioral truth and Sections 4 and 5 as lookup tables.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the role is not permitted for the endpoint per the access matrix, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Five roles exist, spelled exactly as follows: `SystemAdmin`, `Coordinator`, `Agent`, `TitleRep`, `LenderRep`.

When `X-User-Role` is `Coordinator`, `X-User-ID` is the `id` of the acting `Coordinator`; ownership checks on any resource that references a `Coordinator` compare the resource's `coordinator_id` foreign-key field to `X-User-ID`. A coordinator who attempts to mutate a file, subscription, or child resource owned by another coordinator is rejected with `ERR_RESOURCE_NOT_OWNED` (HTTP 403).

When `X-User-Role` is `Agent`, `X-User-ID` is the `id` of the acting `Agent`; ownership checks on any resource that references an `Agent` compare the resource's foreign-key field to `X-User-ID`. An agent submitting a document must be the file's `buyer_agent_id` or `seller_agent_id`, otherwise `ERR_AGENT_NOT_ON_FILE` (HTTP 403). A signing agent whose `X-User-ID` does not match the signature request's `agent_id` is rejected with `ERR_SIGNATURE_NOT_AUTHORIZED` (HTTP 403).

When `X-User-Role` is `SystemAdmin`, `TitleRep`, or `LenderRep`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `author_role` context on `CommunicationEntry` where a transition writes it) but does not compare it to any entity's `id`.

Segregation of duties is deliberate: `SystemAdmin` alone manages coordinators, checklist templates, and the logical clock; `Coordinator` alone owns files, roster, subscription, and every file-lifecycle action; `Agent` alone submits documents and signs or declines signature requests; `TitleRep` alone confirms title clearance; `LenderRep` alone confirms lender clear-to-close. Logging a communication entry is the only mutating operation shared across roles (`Coordinator` and `Agent`), and all `GET` endpoints are readable by every role.

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

List endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0. List results are always sorted by `created_at` ascending. The `meta` envelope on list responses carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity and Common Fields

Every persisted resource carries a server-minted `id` that is a UUID with no type prefix. All entities except `CommunicationEntry` additionally carry `created_at` and `updated_at` (ISO 8601 UTC timestamps with three fractional digits) and an integer `version` that increments by 1 on every mutation of that entity. `CommunicationEntry` is the sole exception: it carries only `id` and `created_at`; both `updated_at` and `version` are absent on that entity.

`updated_at` and `version` change together: any transition, cascade, or computed-field write that mutates an entity refreshes `updated_at` and bumps `version` by exactly 1. Read operations never touch either field.

### 2.5. Validation Order and Request Shape

When several checks could reject the same request, the service evaluates them in a fixed order so the returned error is deterministic. First, header presence and well-formedness (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, role permission (`ERR_INSUFFICIENT_PERMISSIONS`). Third, existence of every path id and body foreign-key id, validated left-to-right as the ids appear in the URL and then the payload; each unresolved id produces its own entity-specific 404 (`ERR_COORDINATOR_NOT_FOUND`, `ERR_AGENT_NOT_FOUND`, `ERR_TEMPLATE_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_FILE_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`, `ERR_DEADLINE_NOT_FOUND`, `ERR_REMINDER_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_COMMUNICATION_NOT_FOUND`, `ERR_AMENDMENT_NOT_FOUND`, `ERR_SIGNATURE_REQUEST_NOT_FOUND`, `ERR_CLOSING_VERIFICATION_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`). Fourth, ownership and scope (`ERR_RESOURCE_NOT_OWNED`, `ERR_AGENT_NOT_ON_FILE`, `ERR_SIGNATURE_NOT_AUTHORIZED`). Fifth, optimistic-concurrency stale-version checks (`ERR_STALE_FILE_VERSION`, `ERR_STALE_SUBSCRIPTION_VERSION`). Sixth, state-machine legality (`ERR_FILE_NOT_DRAFT`, `ERR_FILE_NOT_ACTIVE`, `ERR_FILE_NOT_PENDING_CLOSE`, `ERR_FILE_NOT_CLOSED`, `ERR_FILE_ALREADY_TERMINAL`, `ERR_MILESTONE_INVALID_STATE`, `ERR_DEADLINE_INVALID_STATE`, `ERR_DOCUMENT_INVALID_STATE`, `ERR_AMENDMENT_INVALID_STATE`, `ERR_SIGNATURE_INVALID_STATE`, `ERR_COMMUNICATION_INVALID_STATE`, `ERR_TEMPLATE_INVALID_STATE`, `ERR_SUBSCRIPTION_INVALID_STATE`, `ERR_INVOICE_INVALID_STATE`). Seventh, the compliance gates in their own fixed sub-order — audit passed, then mandatory milestones completed, then no open escalations, then clear-to-close (`ERR_AUDIT_NOT_PASSED`, `ERR_MANDATORY_MILESTONES_OPEN`, `ERR_OPEN_ESCALATIONS`, `ERR_NOT_CLEAR_TO_CLOSE`). Eighth, temporal sanity (`ERR_CLOSING_DATE_IN_PAST`, `ERR_AMENDMENT_DATE_IN_PAST`, `ERR_INVALID_AMENDMENT_WINDOW`, `ERR_RESPONSE_DUE_IN_PAST`). Ninth, business constraints (`ERR_TEMPLATE_ALREADY_ACTIVE`, `ERR_SUBSCRIPTION_ALREADY_ACTIVE`, `ERR_AMENDMENT_IN_FLIGHT`, `ERR_AMENDMENT_WINDOW_OVERLAP`, `ERR_CLOSING_DATE_CONFLICT`, `ERR_MILESTONE_MANDATORY`). Tenth, referential usability (`ERR_TEMPLATE_NOT_FOUND`, `ERR_SUBSCRIPTION_INACTIVE`, `ERR_AGENT_NOT_FOUND`, `ERR_INVALID_REQUEST`). Eleventh, fiscal gates (`ERR_INVOICE_UNPAID`). Twelfth and last, request shape — missing required field, invalid enum member, unknown field (`ERR_INVALID_REQUEST`). The shape check is deliberately lowest priority: a request that fails both a state check and a shape check returns the state error, not the shape error.

### 2.6. Optimistic Concurrency Control

Exactly two write endpoints participate in optimistic concurrency control, each against a named parent entity.

A request that creates an amendment against a transaction file must carry `expected_file_version`, a non-optional field holding the client's last observed `version` of the target `TransactionFile`. If the file's current `version` has advanced since the client last read it — amendment creation itself supersedes any existing draft amendment and increments `file.version`, so a second create carrying the previously observed version is stale — the create is rejected with `ERR_STALE_FILE_VERSION` (HTTP 412).

A request that creates a `SUBSCRIPTION`-billed transaction file must carry `expected_subscription_version`, a non-optional field holding the client's last observed `version` of the target `Subscription`. File creation commits an included-files slot and increments the subscription's `version`, so a create carrying a previously observed version is stale even when quota semantics would otherwise allow the commitment; it is rejected with `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412). Endpoints not named here do not take a version field.

### 2.7. Monetary Precision and Rounding

All money amounts are integer cents; no fractional cents ever appear. Where a computation needs rounding — the per-line charge components of an invoice and the subscription discount — the rule is round-half-up. Two rounding points are pinned: each charge component is rounded to integer cents first, one line per component, and the subscription discount is then computed once on the summed subtotal. Computing the discount per line and then summing is a different, non-conformant order and may differ by cents.

### 2.8. The Logical Clock

Time inside the service is logical, not wall-clock. At startup the current time is exactly 2026-08-01T00:00:00Z and never advances on its own. An administrator-only capability advances the clock to a supplied `to_iso8601` instant. Advancing the clock fires four categories of time-based transitions, in this pinned order: first due reminders are sent, then deadline expiries (each with its escalation cascade), then milestone overdue transitions, then communication-entry escalations. All dates and datetimes the service compares against the clock are measured against this logical time.

### 2.9. Calendar Conventions and Template Version Pinning

Two deadline day-count conventions exist. A file's `state_code` pins which one applies: for `NY`, deadlines count business days; for every other state code, deadlines count calendar days. Under the calendar convention, a deadline's `due_date` is the file's `effective_date` plus `offset_days` calendar days. Under the business convention, `due_date` is the `effective_date` plus `offset_days` business days, counting Monday through Friday only, with the count starting on the day after the `effective_date` (day zero is the `effective_date` itself); holidays are not observed, only weekends. The two conventions produce different due dates for identical inputs, and the business convention always yields a date no earlier than the calendar one for a positive offset.

Checklist templates are versioned. Publishing a template increments its `template_version` by 1 on every publish, and activating a file pins both `template_id` and the then-current `template_version` onto the file. Retiring a template later has no effect on files that already pinned it.

### 2.10. Hierarchical Path Resolution

Where an endpoint path nests one resource under another, path parameters are validated left-to-right: the outer id is resolved first, and only then the inner id, each failure producing the corresponding entity-specific 404 from §2.5 before any deeper check runs.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Coordinators, Agent Rosters, and Checklist Templates

A `SystemAdmin` registers each coordinator by supplying `full_name`, `email`, and `license_number`. The email must be unique across coordinators. A newly registered coordinator starts with `status` set to `ACTIVE`; the only other value it can take is `SUSPENDED`.

Once registered, a `Coordinator` builds a roster by adding agents one at a time, supplying each agent's `full_name`, `email`, and `brokerage`. The roster owner is recorded automatically: the new agent's `coordinator_id` is set from the acting coordinator's `X-User-ID`, and the agent starts with `status` `ACTIVE` (the alternative being `INACTIVE`).

Checklist templates are the platform's unit of jurisdictional knowledge, and only a `SystemAdmin` manages them. Creating a template requires `state_code` (two uppercase letters), `contract_type` (one of `PURCHASE_SALE` or `LISTING_ONLY`), `milestone_defs`, and `required_doc_types`. Each entry of `milestone_defs` is a triple of `name`, `offset_days` (calendar days from a file's `effective_date`), and `mandatory`. `required_doc_types` lists the `doc_type` values the template requires for a compliance audit to pass; it may be empty. A template is created in `DRAFT` with `template_version` 1 and follows the path `DRAFT → ACTIVE → RETIRED`.

Publishing moves a template from `DRAFT` to `ACTIVE`. The template must currently be in `DRAFT` (otherwise `ERR_TEMPLATE_INVALID_STATE`), its `milestone_defs` must be non-empty (otherwise `ERR_INVALID_REQUEST`), and — critically — at most one template may be `ACTIVE` for any given pair of `state_code` and `contract_type`; publishing a second one is rejected with `ERR_TEMPLATE_ALREADY_ACTIVE`. Every publish increments `template_version` by 1. Retiring moves an `ACTIVE` template to `RETIRED` (any other starting state draws `ERR_TEMPLATE_INVALID_STATE`), and retirement is non-destructive: files that already pinned a version of the template keep working against that pinned version forever.

### 3.2. Pricing Agreements: Per-File Billing vs. Subscription

A coordinator chooses between two billing models per file, but the subscription itself is a coordinator-level object created once. Opening a subscription requires `monthly_fee_cents`, `included_files_quota`, and `overage_fee_cents`. The quota is the number of committed file slots included before overage pricing kicks in and may be 0, in which case every file is an overage file. The subscription starts `ACTIVE` with `included_files_used` at 0, and a coordinator may hold at most one `ACTIVE` subscription — a second open attempt is rejected with `ERR_SUBSCRIPTION_ALREADY_ACTIVE`.

Cancelling a subscription is allowed only when it is `ACTIVE` (otherwise `ERR_SUBSCRIPTION_INVALID_STATE`) and only when no transaction file of that subscription is currently in `ACTIVE` or `PENDING_CLOSE` (otherwise `ERR_SUBSCRIPTION_HAS_ACTIVE_FILES`). Cancellation moves it to `CANCELLED`.

The `included_files_used` counter is the subscription's committed-slot ledger: it increases by 1 the moment a file is created under the subscription and decreases by 1 only on an eligible termination release described in §3.6. The counter is what the overage boundary compares against at file-creation time.

### 3.3. Opening a Transaction File

A coordinator opens a transaction file with `billing_model` (`PER_FILE` or `SUBSCRIPTION`), `state_code`, `contract_type` (`PURCHASE_SALE` or `LISTING_ONLY`), `property_address`, `effective_date` in `YYYY-MM-DD` form, `closing_date` in `YYYY-MM-DD` form, `list_price_cents`, `seller_agent_id` (always required), and the contingency offsets `inspection_offset_days`, `appraisal_offset_days`, and `financing_offset_days`, each at least 0. The financing offset may be omitted for cash deals. Two fields are conditionally required: `buyer_agent_id` is required exactly when the contract type is `PURCHASE_SALE` and null is allowed otherwise (a missing buyer agent on a purchase-sale is `ERR_INVALID_REQUEST`); `subscription_id` is required exactly when the billing model is `SUBSCRIPTION` and forbidden otherwise, and it must reference a subscription that exists, is `ACTIVE`, and belongs to the acting coordinator, otherwise `ERR_SUBSCRIPTION_INACTIVE`. Agent ids must resolve on the coordinator's roster (`ERR_AGENT_NOT_FOUND`).

The closing date is validated against the logical clock at creation: a `closing_date` before the current clock date is rejected with `ERR_CLOSING_DATE_IN_PAST`.

A new file is created in `DRAFT`. Its full lifecycle is `DRAFT → ACTIVE → PENDING_CLOSE → CLOSED → ARCHIVED`, with termination possible from `ACTIVE` or `PENDING_CLOSE` into `TERMINATED`. `ARCHIVED` and `TERMINATED` are terminal. The file also carries, from the start, `last_audit_status` initialized to `NONE` (its other values being `PASS` and `FAIL`) and `open_escalation_count` initialized to 0. Fields like `template_id`, `template_version`, `fee_estimate_cents`, `fee_final_cents`, `terminated_reason`, and `archived_at` are populated later by the transitions that own them.

Subscription-billed creation does extra work synchronously. The create request must carry `expected_subscription_version` per §2.6. Before this file's commitment is applied, the service evaluates whether the subscription's `included_files_used` is strictly less than its `included_files_quota`; the boundary is strict, so when the counter equals the quota exactly the new file is an overage commitment. That within-quota verdict is frozen onto the file at creation and reused verbatim by the fee calculations later, independent of how the counter moves afterward. Only then is `included_files_used` incremented by 1 and the subscription's `version` bumped by 1.

### 3.4. Activation: Template Pinning, Milestones, Deadlines, Reminders, and the Estimated Invoice

Activation is the heaviest transition in the system. A coordinator activates a file currently in `DRAFT` (any other state: `ERR_FILE_NOT_DRAFT`). Five preconditions hold: an `ACTIVE` checklist template must exist for the file's pair of `state_code` and `contract_type` (`ERR_TEMPLATE_NOT_FOUND`); when the billing model is `SUBSCRIPTION`, the referenced subscription must exist, be `ACTIVE`, and belong to the acting coordinator (`ERR_SUBSCRIPTION_INACTIVE`); `closing_date` must not be before the current clock date (`ERR_CLOSING_DATE_IN_PAST`); and the closing calendar must have room — no other file of the same coordinator in `ACTIVE` or `PENDING_CLOSE` may have a `closing_date` within one day of this file's, meaning a difference of 0 or 1 day in either direction conflicts with `ERR_CLOSING_DATE_CONFLICT` while 2 or more days is allowed. (The subscription slot itself was already committed at file creation, not here.)

On success, activation pins `template_id` and the template's current `template_version` onto the file, then instantiates the working set. One `Milestone` is created per entry in the template's `milestone_defs`, copying `name`, `offset_days`, and `mandatory` verbatim and computing `due_date` as the file's `effective_date` plus `offset_days` calendar days. Three deadlines are considered: an `INSPECTION` deadline from `inspection_offset_days`, an `APPRAISAL` deadline from `appraisal_offset_days`, and a `FINANCING` deadline only when `financing_offset_days` was provided. Each deadline records its `kind` (`INSPECTION`, `APPRAISAL`, or `FINANCING`), copies its `offset_days` from the corresponding file field, derives its `day_convention` from the file's `state_code` per §2.9 (`BUSINESS` for `NY`, `CALENDAR` otherwise), and computes its `due_date` under that convention. Each deadline then generates its reminder schedule: candidate reminders sit at 5 days before, 2 days before, and on the due date itself, each at 09:00:00 UTC; only candidates whose `scheduled_at` is strictly after the current clock time are actually created, and created reminders are numbered `sequence_no` 1, 2, 3 in ascending `scheduled_at` order. Every reminder starts `QUEUED` with `sent_at` unset.

Finally, activation computes `fee_estimate_cents` and creates the file's one-and-only `Invoice` in `DRAFT` with the estimate's line items. The estimate depends on the billing variant. Under `PER_FILE`, the base is 39500 cents for a `PURCHASE_SALE` contract or 29500 cents for a `LISTING_ONLY` contract, and a rush surcharge of 7500 cents is added when the gap between `closing_date` and the activation date is strictly less than 10 days — a gap of exactly 10 days does not trigger the surcharge. Under `SUBSCRIPTION`, the frozen within-quota verdict decides: if the file committed within quota the estimate is 0 (an included slot); otherwise it is the subscription's `overage_fee_cents` plus the same 7500-cent rush surcharge under the same strictly-less-than-10-days rule. Identical file data therefore prices differently under the two variants.

### 3.5. Working the File: Milestones, Deadlines, Documents, and Communications

Milestones move `PENDING → IN_PROGRESS → COMPLETED`, with `PENDING`, `IN_PROGRESS`, or `OVERDUE` able to go to `WAIVED` (non-mandatory only), any of those three able to go to `CANCELLED` by cascade, and the system able to move `PENDING` or `IN_PROGRESS` to `OVERDUE`. Starting requires the milestone to be `PENDING` (`ERR_MILESTONE_INVALID_STATE`) and the owning file to be `ACTIVE` (`ERR_FILE_NOT_ACTIVE`). Completing requires `IN_PROGRESS` or `OVERDUE` (`ERR_MILESTONE_INVALID_STATE`); it stamps `completed_at` and sets `late_completion` to true exactly when the milestone was completed from `OVERDUE`. Waiving requires `PENDING`, `IN_PROGRESS`, or `OVERDUE` and that `mandatory` be false — waiving a mandatory milestone is `ERR_MILESTONE_MANDATORY`. When the logical clock advances past a milestone's `due_date` while it is still `PENDING` or `IN_PROGRESS`, the system moves it to `OVERDUE`.

Deadlines move `PENDING → MET | WAIVED | CANCELLED`, with the system able to move `PENDING` to `EXPIRED`. Marking met requires the deadline `PENDING` (`ERR_DEADLINE_INVALID_STATE`) and the owning file in `ACTIVE` or `PENDING_CLOSE` (`ERR_FILE_NOT_ACTIVE`); it stamps `met_at` and cancels all of the deadline's `QUEUED` reminders. Waiving requires `PENDING` (`ERR_DEADLINE_INVALID_STATE`) and likewise cancels `QUEUED` reminders. When the clock advances past a `PENDING` deadline's `due_date`, the system moves it to `EXPIRED`: `QUEUED` reminders are cancelled, an escalation communication entry is created on the file with `entry_kind` `ESCALATION`, `party` `SYSTEM`, `direction` `SYSTEM`, and `status` `ESCALATED` — and that creation itself increments the file's `open_escalation_count` by 1 — and the deadline's `escalated` flag is set true. Reminders themselves live in `QUEUED → SENT` (system-driven, when clock time reaches `scheduled_at` and the owning deadline is still `PENDING`, stamping `sent_at`) or `QUEUED → CANCELLED` when their deadline goes terminal or is rescheduled. Each reminder stays linked to its deadline through `deadline_id`, which is also available as a list filter alongside `status` when browsing reminders.

Documents track the compliance paper trail. A coordinator requests a document on a file by naming `file_id` and `doc_type`; the `doc_type` vocabulary is `EXECUTED_CONTRACT`, `INSPECTION_REPORT`, `APPRAISAL_REPORT`, `LOAN_COMMITMENT`, `TITLE_COMMITMENT`, `T47_DISCLOSURE`, `NHD_REPORT`, `TDS_DISCLOSURE`, `HOA_ADDENDUM`, `CLOSING_DISCLOSURE`, `AMENDMENT_EXECUTED`, and `OTHER`. The document starts `REQUESTED` with `review_round` 1. A party agent submits it, moving `REQUESTED → RECEIVED` or, on resubmission, `REJECTED → RECEIVED`; the actor must be the file's buyer or seller agent (`ERR_AGENT_NOT_ON_FILE`), the document must be in `REQUESTED` or `REJECTED` (`ERR_DOCUMENT_INVALID_STATE`), the submit stamps `submitted_by_agent_id` with the acting agent, a resubmission increments `review_round` by 1, and every submission resets the file's `last_audit_status` to `NONE`. The coordinator then accepts (`RECEIVED → ACCEPTED`) or rejects (`RECEIVED → REJECTED`) it; rejection requires a `reason` (otherwise `ERR_INVALID_REQUEST`) which is recorded as `reject_reason`, and both accept and reject also reset the file's `last_audit_status` to `NONE` — any document status mutation after an audit invalidates that audit. File termination cascades any document in `REQUESTED`, `RECEIVED`, or `REJECTED` to `CANCELLED`.

Communication entries are the file's party-contact log, creatable by either a `Coordinator` or an `Agent`. Creating one requires `file_id`, `party` (one of `BUYER_AGENT`, `SELLER_AGENT`, `LENDER`, `TITLE`, `COORDINATOR`, `SYSTEM`), `direction` (`INBOUND`, `OUTBOUND`, or `SYSTEM`), and `body`; `requires_response` defaults to false, and when it is true a `response_due_at` must be supplied that is strictly after the current clock time, otherwise `ERR_RESPONSE_DUE_IN_PAST`. Each entry records `author_role` from the caller's `X-User-Role` and starts `OPEN` with `entry_kind` `LOG` (other kinds being `ESCALATION` and `SYSTEM`). An optional `in_reply_to_id` references another entry on the file; when it references an `OPEN` entry, that referenced entry is marked `ANSWERED`. When the clock advances past `response_due_at` on an `OPEN` entry flagged `requires_response`, the system moves it `OPEN → ESCALATED` and increments the file's `open_escalation_count` by 1. A coordinator resolves an entry in `OPEN` or `ESCALATED` (otherwise `ERR_COMMUNICATION_INVALID_STATE`); resolving an `ESCALATED` entry decrements the file's `open_escalation_count` by 1, while resolving an `OPEN` one leaves the counter untouched.

### 3.6. Amendments: Routing, Signature, and the Effective Cascade

Contract changes are first-class objects. A coordinator drafts an amendment against a file with `file_id`, `expected_file_version` (the OCC field of §2.6), `effective_from`, `effective_to`, and optionally `new_effective_date`, `new_closing_date`, and `new_list_price_cents`. The window is half-open: `effective_from` is inclusive, `effective_to` is exclusive, and `effective_to` must be strictly after `effective_from` (`ERR_INVALID_AMENDMENT_WINDOW`, HTTP 400). A `new_closing_date` in the past at creation is `ERR_AMENDMENT_DATE_IN_PAST`. The new window must not overlap the window of any other amendment of the same file in `ROUTED`, `PARTIALLY_SIGNED`, `FULLY_SIGNED`, or `EFFECTIVE`; half-open semantics mean sharing exactly one boundary date is allowed, and a genuine overlap is `ERR_AMENDMENT_WINDOW_OVERLAP`. Creating an amendment when an older `DRAFT` amendment still exists on the same file supersedes it: the old draft is voided, its `PENDING` signature requests voided with it. The new amendment starts `DRAFT` with `round_number` 1, and the creation itself increments the file's `version` by 1 — which is exactly why the OCC check exists.

Routing moves `DRAFT → ROUTED`. The amendment must be `DRAFT` (`ERR_AMENDMENT_INVALID_STATE`), the owning file must be `ACTIVE` (`ERR_FILE_NOT_ACTIVE`), and no other amendment of the same file may currently be in `ROUTED`, `PARTIALLY_SIGNED`, or `FULLY_SIGNED` (`ERR_AMENDMENT_IN_FLIGHT`). Routing creates the round's `SignatureRequest` rows: for a `PURCHASE_SALE` file, one request for `buyer_agent_id` with `signer_party` `BUYER_AGENT` and one for `seller_agent_id` with `signer_party` `SELLER_AGENT`; for a `LISTING_ONLY` file, only the seller-agent request. Each request carries the round's `round_number`, its parent `amendment_id`, and its `agent_id`, and starts `PENDING` with `signed_at` unset; both `amendment_id` and `agent_id` (alongside `status` and `round_number`) are available as filters when listing signature requests.

Signing and declining belong to the designated agent. Signing requires the request `PENDING` (`ERR_SIGNATURE_INVALID_STATE`), the acting agent's `X-User-ID` to equal the request's `agent_id` (`ERR_SIGNATURE_NOT_AUTHORIZED`), and the owning amendment to be in `ROUTED` or `PARTIALLY_SIGNED` (`ERR_AMENDMENT_INVALID_STATE`). A signature stamps `signed_at` and auto-advances the amendment: the first signature of the round moves `ROUTED → PARTIALLY_SIGNED`, and when every request of the current round is `SIGNED` the amendment becomes `FULLY_SIGNED` (directly from `ROUTED` in the single-signer case, or from `PARTIALLY_SIGNED`). Declining requires the request `PENDING` and the same actor match; a decline — optionally carrying a `reason` — moves the request to `DECLINED`, the owning amendment to `REJECTED`, and every remaining `PENDING` request of the round to `VOIDED`.

A rejected amendment can be revised: revising moves `REJECTED → DRAFT` and increments `round_number` by 1, ready for a fresh routing round. A coordinator may also void any amendment in `DRAFT`, `ROUTED`, `PARTIALLY_SIGNED`, or `FULLY_SIGNED` (otherwise `ERR_AMENDMENT_INVALID_STATE`), moving it to `VOIDED` and voiding its `PENDING` signature requests.

Applying a fully signed amendment is the payoff. The amendment must be `FULLY_SIGNED` (`ERR_AMENDMENT_INVALID_STATE`). Three cascades fire in order. First, the payload lands on the file: `effective_date`, `closing_date`, and `list_price_cents` are replaced wherever the corresponding `new_effective_date`, `new_closing_date`, and `new_list_price_cents` are non-null, and the file's `version` is incremented. Second, the file's `effective_date` change recomputes every non-terminal milestone's `due_date` as the new effective date plus that milestone's `offset_days`, and every `PENDING` deadline's `due_date` via the deadline due-date rule under the file's pinned day convention. Third, each recomputed `PENDING` deadline regenerates its reminders: existing `QUEUED` reminders are cancelled, new future reminders are created per the schedule rule, and `SENT` reminders are preserved untouched and not counted toward the new sequence.

### 3.7. Compliance Audit and the Request-Close Gate

Before a file may approach closing, its paperwork must pass a deterministic audit. A coordinator runs the compliance audit on a file. The required set is built by concatenating the pinned template's `required_doc_types` (in template declaration order) with the state-mandated disclosures for the file's `state_code` (in constant declaration order) — `TX` requires `T47_DISCLOSURE`; `NY` requires `NHD_REPORT`; `CA` requires `TDS_DISCLOSURE` then `NHD_REPORT`; `CO` requires nothing extra — and removing duplicates while keeping each first occurrence. Each required `doc_type` is satisfied exactly when the file has at least one document of that type in `ACCEPTED` status; documents in `REQUESTED`, `RECEIVED`, `REJECTED`, or `CANCELLED` do not count. The unsatisfied types, in required-set order, are returned as `missing_doc_types`, and the `result` is `PASS` exactly when that list is empty — so an empty required set passes with zero documents. The audit writes the file's `last_audit_status` to the result.

Requesting close moves `ACTIVE → PENDING_CLOSE` and enforces the compliance gates in fixed sub-order, so the first failing gate is the reported one: `last_audit_status` must be `PASS` (`ERR_AUDIT_NOT_PASSED`); every mandatory milestone must be `COMPLETED` (`ERR_MANDATORY_MILESTONES_OPEN`); and `open_escalation_count` must be 0 (`ERR_OPEN_ESCALATIONS`). The file must of course be `ACTIVE` first (`ERR_FILE_NOT_ACTIVE`). Success creates the file's one-and-only `ClosingVerification` with `title_status` `PENDING` and `lender_status` initialized to `NOT_REQUIRED` when the file has no `FINANCING` deadline (a cash deal) and to `PENDING` otherwise.

### 3.8. Clear-to-Close, Closing, Invoicing, and Archival

The closing verification is a two-dimensional join with deliberate segregation of duties. A `TitleRep` — and only a `TitleRep` — confirms title clearance, moving `title_status` from `PENDING` to `CLEARED`. A `LenderRep` — and only a `LenderRep` — confirms lender clearance, moving `lender_status` from `PENDING` to `CLEAR_TO_CLOSE` (a `NOT_REQUIRED` lender side never moves). The derived `overall_status` is `CLEAR_TO_CLOSE` exactly when `title_status` is `CLEARED` and `lender_status` is either `CLEAR_TO_CLOSE` or `NOT_REQUIRED`, and `PENDING` otherwise; each confirmation recomputes it.

Closing moves `PENDING_CLOSE → CLOSED`. The file must be in `PENDING_CLOSE` (`ERR_FILE_NOT_PENDING_CLOSE`) and the verification's `overall_status` must be `CLEAR_TO_CLOSE` (`ERR_NOT_CLEAR_TO_CLOSE`). Closing computes the final fee. The amendment component counts only the file's amendments in `EFFECTIVE` status — drafts, routed, partially or fully signed, rejected, and voided amendments are excluded — subtracts the one free amendment with a floor of zero, and multiplies the remainder by 5000 cents each. That amendment fee is added to the activation-time components: under `PER_FILE`, the contract-type base (39500 or 29500 cents) plus the rush surcharge as computed at activation; under `SUBSCRIPTION`, zero if the file committed within quota else the `overage_fee_cents`, again plus the activation-time rush. The evaluation order is fixed: count effective amendments, subtract the free allowance floored at zero, multiply by the per-amendment fee, then add to the activation components. The result is stored as `fee_final_cents`.

The close also rebuilds the file's invoice to its final line set. The invoice's `line_items` array carries one entry per charge component, each entry a `label` drawn from `BASE_FEE`, `RUSH_SURCHARGE`, `SUBSCRIPTION_OVERAGE`, `SUBSCRIPTION_INCLUDED`, `AMENDMENT_FEE`, and `TERMINATION_CREDIT`, paired with an integer `amount_cents`. The `subtotal_cents` is the sum of the per-line amounts, each line already rounded to integer cents before summing — the raw sum is never rounded. When the billing model is `SUBSCRIPTION`, a `discount_cents` of the subtotal multiplied by 5 percent, rounded half-up, is computed once on that summed subtotal; under `PER_FILE` the discount is 0. The `total_cents` is the subtotal minus the discount. On close, the rebuilt invoice moves from `DRAFT` to `ISSUED` with `issued_at` stamped. A coordinator may also issue a `DRAFT` invoice manually while the owning file is `ACTIVE` or `CLOSED` (otherwise `ERR_INVOICE_INVALID_STATE` or `ERR_FILE_NOT_ACTIVE`), and may mark an `ISSUED` invoice `PAID` (any other starting state: `ERR_INVOICE_INVALID_STATE`).

Archival is the last step, moving `CLOSED → ARCHIVED`. The file must be `CLOSED` (`ERR_FILE_NOT_CLOSED`) and its invoice must be `PAID` (`ERR_INVOICE_UNPAID`, HTTP 402). Archival stamps `archived_at` with the current clock time and renders the file read-only: the post-close archive is immutable from then on.

### 3.9. Termination: The Full Cancellation Cascade

Terminating a file in `ACTIVE` or `PENDING_CLOSE` moves it to `TERMINATED`; targeting a file already in a terminal state is `ERR_FILE_ALREADY_TERMINAL`. The request may carry an optional `reason`, recorded as `terminated_reason`. Termination fires a five-part cascade, every part of which an implementer must reproduce.

Cascade one: every milestone in `PENDING`, `IN_PROGRESS`, or `OVERDUE` moves to `CANCELLED`. Cascade two: every deadline in `PENDING` moves to `CANCELLED`, and that cancellation itself cancels all of the deadline's `QUEUED` reminders. Cascade three: every amendment in `DRAFT`, `ROUTED`, `PARTIALLY_SIGNED`, or `FULLY_SIGNED` moves to `VOIDED`, and that voiding itself voids all of the amendment's `PENDING` signature requests. Cascade four: every communication entry in `OPEN` or `ESCALATED` moves to `RESOLVED`, and the file's `open_escalation_count` is reset to 0. Cascade five: an invoice still in `DRAFT` moves to `VOIDED` with `TERMINATION_CREDIT` lines appended — one per existing charge line, each with an amount equal to the negated charge amount — so the net line sum is 0 and both `subtotal_cents` and `total_cents` become 0.

One conditional release follows: when the file's billing model is `SUBSCRIPTION` and no document on the file ever reached `ACCEPTED`, the subscription's `included_files_used` is decremented by 1 and the subscription's `version` is bumped by 1 — the slot is handed back. If any document was accepted, the slot is forfeit. A `ClosingVerification` that already exists is left with its `overall_status` unchanged; the file is simply terminal.

### 3.10. The Clock Sweep in Detail

Because deadlines, reminders, overdue flags, and escalations all hang off the logical clock, its sweep order matters and is fixed: due reminders are sent first (`QUEUED → SENT` where `scheduled_at` has been reached and the owning deadline is still `PENDING`); then deadline expiries (`PENDING → EXPIRED`, each with the escalation-entry creation and counter increment of §3.5); then milestone overdue transitions (`PENDING`/`IN_PROGRESS → OVERDUE` where the clock date has passed `due_date`); then communication escalations (`OPEN → ESCALATED` where `requires_response` is true and the clock has passed `response_due_at`). The sweep response reports `reminders_sent`, `deadlines_expired`, `milestones_marked_overdue`, and `communications_escalated` counts.

## 4. Endpoint Definitions

All endpoints are mounted under the `/tc` prefix. Resource-creating endpoints return 201 with the created resource; state transitions, modifications, and reads return 200. Error responses use the envelope of §2.2 with the codes of §5. List endpoints follow §2.3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /tc/coordinators | Register a coordinator | SystemAdmin |
| GET | /tc/coordinators/{coordinatorId} | Get a coordinator | SystemAdmin, Coordinator, Agent, TitleRep, LenderRep |
| POST | /tc/agents | Add an agent to the acting coordinator's roster | Coordinator |
| GET | /tc/agents/{agentId} | Get an agent | SystemAdmin, Coordinator, Agent, TitleRep, LenderRep |
| GET | /tc/agents | List agents, optionally by roster owner | SystemAdmin, Coordinator, Agent, TitleRep, LenderRep |
| POST | /tc/checklist-templates | Create a template for a (state, contract type) pair | SystemAdmin |
| GET | /tc/checklist-templates/{templateId} | Get a template | SystemAdmin, Coordinator, Agent, TitleRep, LenderRep |
| GET | /tc/checklist-templates | List templates | SystemAdmin, Coordinator, Agent, TitleRep, LenderRep |
| POST | /tc/checklist-templates/{templateId}/publish | Publish a template (one ACTIVE per pair) | SystemAdmin |
| POST | /tc/checklist-templates/{templateId}/retire | Retire an ACTIVE template | SystemAdmin |
| POST | /tc/subscriptions | Open a subscription for the acting coordinator | Coordinator |
| GET | /tc/subscriptions/{subscriptionId} | Get a subscription | SystemAdmin, Coordinator, Agent, TitleRep, LenderRep |
| GET | /tc/subscriptions | List subscriptions | SystemAdmin, Coordinator, Agent, TitleRep, LenderRep |
| POST | /tc/subscriptions/{subscriptionId}/cancel | Cancel a subscription with no active files | Coordinator |
| POST | /tc/files | Create a transaction file in DRAFT (SUBSCRIPTION commits a slot, OCC on subscription version) | Coordinator |
| GET | /tc/files/{fileId} | Get a transaction file | SystemAdmin, Coordinator, Agent, TitleRep, LenderRep |
| GET | /tc/files | List transaction files | SystemAdmin, Coordinator, Agent, TitleRep, LenderRep |
| POST | /tc/files/{fileId}/activate | Activate a DRAFT file (pins template; instantiates milestones, deadlines, reminders, invoice) | Coordinator |
| POST | /tc/files/{fileId}/terminate | Terminate an ACTIVE/PENDING_CLOSE file with the full cascade | Coordinator |
| POST | /tc/files/{fileId}/request-close | Request close (audit PASS, mandatory milestones done, no open escalations); creates ClosingVerification | Coordinator |
| POST | /tc/files/{fileId}/close | Close once CLEAR_TO_CLOSE; finalizes fee and issues invoice | Coordinator |
| POST | /tc/files/{fileId}/archive | Archive a CLOSED file whose invoice is PAID | Coordinator |
| POST | /tc/files/{fileId}/compliance-audit | Run the compliance audit; sets last_audit_status | Coordinator |
| GET | /tc/milestones/{milestoneId} | Get a milestone | SystemAdmin, Coordinator, Agent, TitleRep, LenderRep |
| GET | /tc/milestones | List milestones | SystemAdmin, Coordinator, Agent, TitleRep, LenderRep |
| POST | /tc/milestones/{milestoneId}/start | Start a PENDING milestone | Coordinator |
| POST | /tc/milestones/{milestoneId}/complete | Complete an IN_PROGRESS or OVERDUE milestone | Coordinator |
| POST | /tc/milestones/{milestoneId}/waive | Waive a non-mandatory milestone | Coordinator |
| GET | /tc/deadlines/{deadlineId} | Get a deadline | SystemAdmin, Coordinator, Agent, TitleRep, LenderRep |
| GET | /tc/deadlines | List deadlines | SystemAdmin, Coordinator, Agent, TitleRep, LenderRep |
| POST | /tc/deadlines/{deadlineId}/mark-met | Mark a PENDING deadline met; cancels its QUEUED reminders | Coordinator |
| POST | /tc/deadlines/{deadlineId}/waive | Waive a PENDING deadline; cancels its QUEUED reminders | Coordinator |
| GET | /tc/reminders/{reminderId} | Get a reminder | SystemAdmin, Coordinator, Agent, TitleRep, LenderRep |
| GET | /tc/reminders | List reminders | SystemAdmin, Coordinator, Agent, TitleRep, LenderRep |
| POST | /tc/documents | Request a document on a file | Coordinator |
| GET | /tc/documents/{documentId} | Get a document | SystemAdmin, Coordinator, Agent, TitleRep, LenderRep |
| GET | /tc/documents | List documents | SystemAdmin, Coordinator, Agent, TitleRep, LenderRep |
| POST | /tc/documents/{documentId}/submit | Party agent submits a REQUESTED or REJECTED document | Agent |
| POST | /tc/documents/{documentId}/accept | Accept a RECEIVED document | Coordinator |
| POST | /tc/documents/{documentId}/reject | Reject a RECEIVED document with a reason | Coordinator |
| POST | /tc/communications | Log a party communication; in_reply_to_id answers an OPEN entry | Coordinator, Agent |
| GET | /tc/communications/{communicationId} | Get a communication entry | SystemAdmin, Coordinator, Agent, TitleRep, LenderRep |
| GET | /tc/communications | List communication entries | SystemAdmin, Coordinator, Agent, TitleRep, LenderRep |
| POST | /tc/communications/{communicationId}/resolve | Resolve an OPEN or ESCALATED entry | Coordinator |
| POST | /tc/amendments | Draft an amendment (OCC on file version; supersedes an existing DRAFT) | Coordinator |
| GET | /tc/amendments/{amendmentId} | Get an amendment | SystemAdmin, Coordinator, Agent, TitleRep, LenderRep |
| GET | /tc/amendments | List amendments | SystemAdmin, Coordinator, Agent, TitleRep, LenderRep |
| POST | /tc/amendments/{amendmentId}/route | Route a DRAFT amendment; creates the round's signature requests | Coordinator |
| POST | /tc/amendments/{amendmentId}/revise | Revise a REJECTED amendment back to DRAFT | Coordinator |
| POST | /tc/amendments/{amendmentId}/apply | Apply a FULLY_SIGNED amendment; cascades date recomputation | Coordinator |
| POST | /tc/amendments/{amendmentId}/void | Void a non-terminal amendment | Coordinator |
| GET | /tc/signature-requests/{signatureRequestId} | Get a signature request | SystemAdmin, Coordinator, Agent, TitleRep, LenderRep |
| GET | /tc/signature-requests | List signature requests | SystemAdmin, Coordinator, Agent, TitleRep, LenderRep |
| POST | /tc/signature-requests/{signatureRequestId}/sign | Sign a PENDING signature request (designated agent only) | Agent |
| POST | /tc/signature-requests/{signatureRequestId}/decline | Decline a PENDING signature request; rejects the round | Agent |
| GET | /tc/closing-verifications/{closingVerificationId} | Get a closing verification | SystemAdmin, Coordinator, Agent, TitleRep, LenderRep |
| GET | /tc/closing-verifications | List closing verifications | SystemAdmin, Coordinator, Agent, TitleRep, LenderRep |
| POST | /tc/closing-verifications/{closingVerificationId}/confirm-title | Title representative confirms title clearance | TitleRep |
| POST | /tc/closing-verifications/{closingVerificationId}/confirm-lender | Lender representative confirms clear-to-close | LenderRep |
| GET | /tc/invoices/{invoiceId} | Get an invoice | SystemAdmin, Coordinator, Agent, TitleRep, LenderRep |
| GET | /tc/invoices | List invoices | SystemAdmin, Coordinator, Agent, TitleRep, LenderRep |
| POST | /tc/invoices/{invoiceId}/issue | Manually issue a DRAFT invoice while the file is ACTIVE or CLOSED | Coordinator |
| POST | /tc/invoices/{invoiceId}/mark-paid | Mark an ISSUED invoice paid | Coordinator |
| POST | /tc/_clock/set_current_utc | Advance the logical clock; fires time-based transitions in pinned order | SystemAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_RESOURCE_NOT_OWNED | 403 |
| ERR_AGENT_NOT_ON_FILE | 403 |
| ERR_SIGNATURE_NOT_AUTHORIZED | 403 |
| ERR_COORDINATOR_NOT_FOUND | 404 |
| ERR_AGENT_NOT_FOUND | 404 |
| ERR_TEMPLATE_NOT_FOUND | 404 |
| ERR_SUBSCRIPTION_NOT_FOUND | 404 |
| ERR_FILE_NOT_FOUND | 404 |
| ERR_MILESTONE_NOT_FOUND | 404 |
| ERR_DEADLINE_NOT_FOUND | 404 |
| ERR_REMINDER_NOT_FOUND | 404 |
| ERR_DOCUMENT_NOT_FOUND | 404 |
| ERR_COMMUNICATION_NOT_FOUND | 404 |
| ERR_AMENDMENT_NOT_FOUND | 404 |
| ERR_SIGNATURE_REQUEST_NOT_FOUND | 404 |
| ERR_CLOSING_VERIFICATION_NOT_FOUND | 404 |
| ERR_INVOICE_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_STALE_FILE_VERSION | 412 |
| ERR_STALE_SUBSCRIPTION_VERSION | 412 |
| ERR_FILE_NOT_DRAFT | 409 |
| ERR_FILE_NOT_ACTIVE | 409 |
| ERR_FILE_NOT_PENDING_CLOSE | 409 |
| ERR_FILE_NOT_CLOSED | 409 |
| ERR_FILE_ALREADY_TERMINAL | 409 |
| ERR_MILESTONE_INVALID_STATE | 409 |
| ERR_DEADLINE_INVALID_STATE | 409 |
| ERR_DOCUMENT_INVALID_STATE | 409 |
| ERR_AMENDMENT_INVALID_STATE | 409 |
| ERR_SIGNATURE_INVALID_STATE | 409 |
| ERR_COMMUNICATION_INVALID_STATE | 409 |
| ERR_TEMPLATE_INVALID_STATE | 409 |
| ERR_SUBSCRIPTION_INVALID_STATE | 409 |
| ERR_INVOICE_INVALID_STATE | 409 |
| ERR_AUDIT_NOT_PASSED | 409 |
| ERR_MANDATORY_MILESTONES_OPEN | 409 |
| ERR_OPEN_ESCALATIONS | 409 |
| ERR_NOT_CLEAR_TO_CLOSE | 409 |
| ERR_CLOSING_DATE_IN_PAST | 422 |
| ERR_AMENDMENT_DATE_IN_PAST | 422 |
| ERR_INVALID_AMENDMENT_WINDOW | 400 |
| ERR_RESPONSE_DUE_IN_PAST | 422 |
| ERR_TEMPLATE_ALREADY_ACTIVE | 409 |
| ERR_SUBSCRIPTION_ALREADY_ACTIVE | 409 |
| ERR_AMENDMENT_IN_FLIGHT | 409 |
| ERR_AMENDMENT_WINDOW_OVERLAP | 409 |
| ERR_CLOSING_DATE_CONFLICT | 409 |
| ERR_MILESTONE_MANDATORY | 409 |
| ERR_SUBSCRIPTION_HAS_ACTIVE_FILES | 409 |
| ERR_SUBSCRIPTION_INACTIVE | 409 |
| ERR_INVOICE_UNPAID | 402 |
