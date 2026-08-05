# Pole-Attachment & Joint-Use Management API — Product Requirements Document

## 1. Introduction

Utilities that own distribution poles rarely use every inch of them alone. Cable operators, telecom carriers, and wireless providers all seek to hang their own lines and equipment on someone else's poles, and the governing framework — pole-attachment and joint-use administration — is a dense mix of engineering, contract law, and federal timing rules. This API is the system of record for that entire relationship: it holds the pole inventory and the owners behind it, receives attachment applications from third-party attachers, schedules make-ready field surveys, prices the engineering and rental fees, tracks each permit against the FCC shot clock, records field audits of unauthorized attachments, and settles the resulting invoices and disputes.

The platform is designed around a strict separation between the parties who plan work and the parties who authorize it, so that no single actor can both survey a pole and grant the permit that follows. It is equally concerned with fiscal accuracy: every reserved inch of communication space, every make-ready labor hour, and every back-rental dollar must be traceable and reproducible to the cent. This document specifies the data model, the state machines that govern each entity's lifecycle, the calculation rules that price the work, and the validation and access-control rules that keep the whole arrangement defensible.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that hold across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well formed but the role is not permitted to perform the requested operation — or an attacher attempts to act on a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly five roles: `JointUseCoordinator`, `Engineer`, `PermitOfficer`, `FieldAuditor`, and `Attacher`.

Four of these roles carry an **opaque** identity. When `X-User-Role` is `JointUseCoordinator`, `Engineer`, `PermitOfficer`, or `FieldAuditor`, the value of `X-User-ID` is an operator identifier that is not tied to any persisted entity; the server may record it where a workflow calls for it — for example, an `Engineer`'s `X-User-ID` is written onto a survey as `surveyor_user_id`, a `PermitOfficer`'s onto an application as `permit_officer_user_id`, and a `FieldAuditor`'s onto a finding as `auditor_user_id` — but it is never compared to any entity's `id`.

The `Attacher` role is **entity-backed**. When `X-User-Role` is `Attacher`, `X-User-ID` is the `id` of the acting `Attacher` entity. Ownership checks on any resource that references an attacher compare the resource's attacher foreign key to `X-User-ID`: an attacher may act only on applications, attachments, invoices, and disputes whose `attacher_id` equals its own `X-User-ID`, and an ownership mismatch is an `ERR_UNAUTHORIZED` rejection.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless otherwise stated, list endpoints return their resources sorted by `created_at` in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every entity in the system carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, recorded when the resource is first created. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. The `version` field is an integer that starts at 1 and increments by one on each mutation; it underpins the optimistic concurrency mechanism described in §2.6. All ten resource types — pole owners, make-ready crews, poles, attachers, attachment applications, make-ready surveys, attachments, unauthorized-attachment findings, invoices, and disputes — expose all four of these fields.

When a computed field such as a pole's `occupied_space_inches` or an attacher's `account_balance_cents` changes as a side effect of another operation, that change is itself a mutation of the owning resource: its `updated_at` is refreshed and its `version` is incremented.

### 2.5. Referential Integrity and Nested Resolution

Many resources reference others by foreign key rather than by URL nesting — an application names a `pole_id` and an `attacher_id`, a survey names an `application_id` and a `crew_id`, and so on. Whenever a request carries a path identifier or a foreign-key input, the referenced resources are resolved left-to-right, and the first identifier that fails to resolve determines the error. A path identifier that does not exist yields the resource-specific not-found error — `ERR_POLE_OWNER_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_POLE_NOT_FOUND`, `ERR_ATTACHER_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_SURVEY_NOT_FOUND`, `ERR_ATTACHMENT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, or `ERR_DISPUTE_NOT_FOUND` as appropriate.

Two uniqueness constraints are enforced at registration. An attacher's `cin` is globally unique; a second registration of the same value is rejected with `ERR_DUPLICATE_CIN`. A pole's `tag` is unique within its owner; a second pole carrying the same `tag` under the same `pole_owner_id` is rejected with `ERR_DUPLICATE_POLE_TAG`.

### 2.6. Optimistic Concurrency on Engineering Estimates

Issuing or re-issuing an engineering estimate is the one mutation guarded by optimistic concurrency control. A request to issue an estimate must carry `expected_application_version` as a required input field, holding the client's last observed `version` of the target `AttachmentApplication`. If that value does not match the application's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Because a prior estimate issuance legitimately supersedes the fee preview and increments the application's `version` by one, a subsequent issuance that still carries the older `expected_application_version` will fail the stale-version check — this is the intended guard against an engineer overwriting an estimate revision they never observed. No other endpoint accepts or requires a version field.

### 2.7. Monetary Values, Space Units, and Precision

All monetary amounts are stored and returned as integer cents. Whenever a calculation produces a fractional cent, the result is rounded half-up to the nearest whole cent. Where a total is assembled from several rounded lines, the rounding is applied to each line first and the rounded lines are then summed, as detailed in the rental calculations of §3.7. Rates supplied as inputs — an owner's `annual_rental_rate_cents` and `make_ready_labor_rate_cents_per_hour` — are stored exactly as provided. Vertical space on a pole is measured in whole inches.

### 2.8. Space Accounting and Balance Conservation

Two derived quantities are maintained as strict aggregations and must always equal their defining sums. A pole's `occupied_space_inches` is the sum of `allotted_space_inches` over every `Attachment` on that pole whose `status` is `ACTIVE`; it starts at zero and is recomputed on every attachment create, transfer, abandon, permit grant, and finding legalization. A pole's `reserved_space_inches` is the sum of `reserved_space_inches` over every `AttachmentApplication` on that pole currently in `ESTIMATE_ACCEPTED`; it starts at zero. These forward and compensating movements are designed to conserve: a transfer removes the old attachment from the `ACTIVE` set and adds the new one, leaving occupancy net unchanged, while an abandonment releases space back.

An attacher's `account_balance_cents` is the sum of `amount_cents` over every `Invoice` billed to that attacher whose `status` is `ISSUED` or `OVERDUE`; it starts at zero and is recomputed whenever an invoice is issued, paid, voided, or has its amount adjusted. Issuance raises the balance; payment, voiding, and downward adjustment lower it.

### 2.9. The Logical Clock and Scheduled Transitions

The system runs on a logical clock rather than wall-clock time. At server startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any clock is set it stays at that default and never falls back to real time. A `JointUseCoordinator` may advance the clock by supplying a target instant as `to_iso8601`. Advancing the clock triggers two scheduled sweeps: every `Invoice` still `ISSUED` whose `due_at` is now in the past transitions to `OVERDUE`, and every `AttachmentApplication` still `ESTIMATE_ISSUED` whose `estimate_expires_at` is now in the past transitions to `ESTIMATE_EXPIRED`. All timestamps written by the system — `submitted_at`, `surveyed_at`, `estimate_issued_at`, `estimate_accepted_at`, `permit_issued_at`, `issued_at`, `audited_at`, and the like — are read from this logical clock.

### 2.10. Validation Precedence

When several checks could reject the same request, they are evaluated in a fixed order so that the reported error is deterministic. Authentication comes first: a missing or unknown user context yields `ERR_UNAUTHENTICATED` (401). Next is role and ownership authorization, yielding `ERR_UNAUTHORIZED` (403). Then existence of every path and foreign-key resource, yielding the appropriate not-found error (404). Then body well-formedness — required fields present, enums valid, integers positive where required, and a survey window whose end is after its start — yielding `ERR_VALIDATION` (422), or `ERR_INVALID_WINDOW` (422) for the window-specific case. Then the target's state validity for the requested transition, yielding `ERR_INVALID_STATE` (409) or a more specific state error. Then optimistic concurrency, yielding `ERR_STALE_VERSION` (412). Then segregation of duties on permit decisions, yielding `ERR_SEGREGATION_OF_DUTIES` (403). Then cross-entity state guards (409). Then crew scheduling conflicts, yielding `ERR_CREW_DOUBLE_BOOKED` (409). Then vertical clearance, yielding `ERR_CLEARANCE_VIOLATION` (409). Then pole capacity, yielding `ERR_INSUFFICIENT_POLE_SPACE` (409). Finally the credit-limit check, yielding `ERR_CREDIT_LIMIT_EXCEEDED` (402). A check earlier in this ordering always masks a check later in it.

## 3. Business Logic & Workflows

### 3.1. Establishing the Joint-Use Network

A `JointUseCoordinator` seeds the system with its participants. Registering a pole owner captures the utility's `legal_name`, its `owner_category` — one of `ELECTRIC_UTILITY`, `ILEC`, or `MUNICIPAL` — the `annual_rental_rate_cents` charged per twelve inches of occupied communication space per year, and the `make_ready_labor_rate_cents_per_hour` that later drives make-ready pricing. Each owner may field one or more make-ready crews; a crew is registered under a `pole_owner_id` with a `crew_name` and a `region` tag.

Poles are registered under an owner as well, each carrying a `pole_owner_id`, an owner-scoped `tag`, an informational total `height_ft`, and the `usable_communication_space_inches` available for attachments. A freshly registered pole begins with `occupied_space_inches` and `reserved_space_inches` both at zero and `status` set to `ACTIVE`.

Attaching companies are registered independently. An attacher record holds a `company_name`, a globally unique `cin`, a `contact_email` for billing and notices, and a `credit_limit_cents` that defaults to 5,000,000 cents when omitted. Its `account_balance_cents` opens at zero and thereafter tracks the attacher's outstanding invoices.

### 3.2. Applying to Attach and the Make-Ready Survey

An `Attacher` opens the process by submitting an attachment application, naming the target `pole_id`, its own `attacher_id`, the `requested_space_inches` of communication space it needs, the `requested_position_inches` giving the intended height above ground, and a `purpose` of `FIBER`, `COAX`, `POWER_SUPPLY`, or `WIRELESS`. Both the requested space and the requested position must be greater than zero. On submission the application enters `SUBMITTED`, its `submitted_at` is stamped from the clock, and its `survey_deadline` is set to forty-five days after submission — the FCC survey shot clock.

From `SUBMITTED`, an `Engineer` conducts the make-ready survey, advancing the application `SUBMITTED → SURVEYED`. The survey call books a crew and describes the field work: it carries a `crew_id`, a `window_start` and `window_end` bounding the field-work window, the `estimated_labor_hours`, a `make_ready_required` flag stating whether any make-ready work is needed at all, an `existing_attacher_count` giving how many incumbent attachers' lines must be transferred, a `complexity_class` of `SIMPLE` or `COMPLEX`, and free-text `findings`. Four preconditions gate the survey: the pole must be `ACTIVE` or the request is rejected with `ERR_POLE_NOT_ACTIVE`; the crew must exist and belong to the same owner as the pole, failing which the response is `ERR_CREW_NOT_FOUND`; the window's `window_end` must be strictly later than its `window_start`, else `ERR_INVALID_WINDOW`; and the chosen crew must not already hold another survey window that overlaps the requested one. Crew windows are treated as half-open intervals from `window_start` up to but not including `window_end`, so two windows that merely touch at an endpoint are allowed, but any true overlap is rejected with `ERR_CREW_DOUBLE_BOOKED`.

A successful survey creates a `MakeReadySurvey` whose `application_id` and `crew_id` tie it to the application and crew, records the submitting engineer's `X-User-ID` as `surveyor_user_id` on both the survey and the application, copies the survey's `make_ready_required` onto the application, stamps `surveyed_at` from the clock, and sets the application's `estimate_deadline` to fourteen days after `surveyed_at` — the estimate shot clock.

### 3.3. Pricing the Estimate and the Attacher's Decision

Once an application is `SURVEYED`, the same `Engineer` staff issue the engineering estimate, advancing it `SURVEYED → ESTIMATE_ISSUED`. This call is also re-callable while the application is already `ESTIMATE_ISSUED`, in which case it recomputes and supersedes the prior fee preview and remains in `ESTIMATE_ISSUED`. Every issuance carries `expected_application_version` and is subject to the stale-version rejection described in §2.6; each successful issuance refreshes `estimate_issued_at` to the current clock, sets `estimate_expires_at` to thirty days after `estimate_issued_at`, computes the make-ready fee estimate and an annual-rental preview, and increments the application's `version` by one.

The **make-ready fee** is priced from the survey. Begin with the owner's `make_ready_labor_rate_cents_per_hour` as the labor rate and a complexity multiplier of 1.75 when `complexity_class` is `COMPLEX` and 1.0 when it is `SIMPLE`. If `make_ready_required` is false, the base labor component is zero; otherwise the base labor is the labor hours multiplied by the labor rate and then by the complexity multiplier. A transfer cost is added for incumbent lines: `existing_attacher_count` multiplied by 7,500 cents each. The subtotal is the base labor plus the transfer cost. The **estimate variant**, computed here at issuance, uses the surveyed `estimated_labor_hours` as the labor hours and then inflates the subtotal by a fifteen-percent contingency buffer — the subtotal multiplied by 1.15 — with the result rounded half-up to whole cents and stored as `make_ready_fee_estimate_cents`. (The **final variant**, computed later at permit grant, is described in §3.4.)

The acting `Attacher` then accepts or rejects the estimate by supplying a `decision`. Rejection moves the application `ESTIMATE_ISSUED → ESTIMATE_REJECTED` with no financial effect. Acceptance moves it `ESTIMATE_ISSUED → ESTIMATE_ACCEPTED` and is gated by four conditions evaluated in the precedence of §2.10: the caller must own the application, or `ERR_UNAUTHORIZED`; the estimate must not have expired — the application must still be `ESTIMATE_ISSUED` and not `ESTIMATE_EXPIRED` — or the acceptance is rejected with `ERR_ESTIMATE_EXPIRED`; the `requested_space_inches` must be no greater than the pole's `usable_communication_space_inches` less its `occupied_space_inches` and less its `reserved_space_inches`, or `ERR_INSUFFICIENT_POLE_SPACE`; and the attacher's `account_balance_cents` plus the `make_ready_fee_estimate_cents` must not exceed its `credit_limit_cents`, or `ERR_CREDIT_LIMIT_EXCEEDED`. On acceptance the application's `reserved_space_inches` is set equal to `requested_space_inches`, raising the pole's `reserved_space_inches`; a `MAKE_READY` invoice is issued for the `make_ready_fee_estimate_cents` and its id recorded as `make_ready_invoice_id`, raising the attacher's `account_balance_cents`; `estimate_accepted_at` is stamped from the clock; and `permit_deadline` is set to sixty days after acceptance — the permit shot clock.

### 3.4. Permitting: Grant, Denial, and the Four-Eyes Rule

An application in `ESTIMATE_ACCEPTED` awaits a `PermitOfficer`, who rules by supplying a `decision` and, on a grant, the `actual_labor_hours` the crew reported. Both outcomes are barred to the engineer who signed the survey: if the officer's `X-User-ID` equals the application's `surveyor_user_id`, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`, enforcing four-eyes separation between surveying and permitting.

A denial moves the application `ESTIMATE_ACCEPTED → PERMIT_DENIED`. It records `permit_officer_user_id`, sets `permit_decision` to `DENIED`, stamps `permit_issued_at`, releases the reservation by returning the application's `reserved_space_inches` to zero (lowering the pole's `reserved_space_inches`), and cascades to the make-ready invoice: the invoice identified by `make_ready_invoice_id` transitions to `VOID`, and because a voided invoice leaves the outstanding set, the attacher's `account_balance_cents` is recomputed downward.

A grant moves the application `ESTIMATE_ACCEPTED → PERMIT_GRANTED` and is additionally gated by a vertical-clearance check. The new attachment will occupy the interval from `requested_position_inches` up to `requested_position_inches` plus `requested_space_inches`. Every `ACTIVE` attachment must sit at least `CLEARANCE_INCHES` (which is 12 inches) clear of the new one: for each existing `ACTIVE` attachment on the pole, the gap between its interval and the new interval — measured between their nearest endpoints, and treated as negative when the two intervals overlap — must be at least 12 inches. If any existing `ACTIVE` attachment lies within 12 inches of the new interval (that is, the gap is strictly less than 12 inches, including any overlap), the grant is rejected with `ERR_CLEARANCE_VIOLATION`. On a clean grant the officer's `X-User-ID` is recorded as `permit_officer_user_id`, `permit_decision` is set to `GRANTED`, and `permit_issued_at` is stamped. The `shot_clock_status` is then computed: it is `ON_TIME` when `permit_issued_at` is on or before `permit_deadline` and `LATE` otherwise, with the boundary treated as on-time.

The grant also settles the make-ready fee. The **final variant** of the make-ready fee is computed exactly as the estimate variant but using the reported `actual_labor_hours` in place of the estimated hours and applying no contingency buffer — the subtotal is rounded half-up directly and stored as `make_ready_fee_final_cents`. The `MAKE_READY` invoice's `amount_cents` is trued up to this final fee, and the attacher's `account_balance_cents` is recomputed accordingly. A new `Attachment` is created on the pole in state `ACTIVE` with `authorized` set to true, `allotted_space_inches` equal to `requested_space_inches`, and `position_inches` equal to `requested_position_inches`; the reservation is converted to occupancy, so the application's `reserved_space_inches` returns to zero while the pole's `occupied_space_inches` rises by the allotted amount.

Finally the grant issues first-year rent. The **first-year proration** computes a full-year figure equal to the owner's `annual_rental_rate_cents` multiplied by the attachment's `allotted_space_inches` and divided by twelve. It then counts the remaining days in the calendar year of `permit_issued_at` inclusive of that day — the days from the permit date through December 31 of that year, counting both ends. The prorated `annual_rental_fee_cents` is the full-year figure multiplied by those remaining days, divided by 365, and rounded half-up to whole cents. A first-year `ANNUAL_RENTAL` invoice is issued for that amount and the attacher's `account_balance_cents` is recomputed upward.

At any point before it reaches a terminal outcome, the acting `Attacher` may withdraw the application, moving it to `WITHDRAWN` from `SUBMITTED`, `SURVEYED`, `ESTIMATE_ISSUED`, or `ESTIMATE_ACCEPTED`; a withdrawal by anyone other than the owning attacher is `ERR_UNAUTHORIZED`. Withdrawing from the first three states has no financial effect. Withdrawing from `ESTIMATE_ACCEPTED` mirrors a denial's cleanup: the reservation is released back to zero (lowering the pole's `reserved_space_inches`) and the make-ready invoice named by `make_ready_invoice_id` is voided, with the attacher's `account_balance_cents` recomputed downward.

### 3.5. Living Attachments: Transfer and Abandonment

A granted `Attachment` records its `pole_id`, its owning `attacher_id`, and the `application_id` of the granting application, along with its system-set `allotted_space_inches` and `position_inches`. The owning `Attacher` may transfer it to another company or abandon it outright.

A transfer advances the attachment `ACTIVE → TRANSFERRED`. The caller must own the attachment, or `ERR_UNAUTHORIZED`, and the supplied `new_attacher_id` must reference an existing attacher, or `ERR_ATTACHER_NOT_FOUND`. The old attachment moves to `TRANSFERRED`, and a fresh `Attachment` is created in `ACTIVE` on the same pole with the same `allotted_space_inches` and `position_inches`, `authorized` true, owned by the new attacher, and carrying `transferred_from_attacher_id` set to the prior owner as an audit pointer. Because the old attachment leaves the `ACTIVE` set as the new one enters it, the pole's `occupied_space_inches` is net unchanged. The endpoint's response body is the addressed attachment — the original one it is keyed on, now in `TRANSFERRED` — rather than the newly created `ACTIVE` attachment.

An abandonment advances the attachment `ACTIVE → ABANDONED`; again the caller must own it or the response is `ERR_UNAUTHORIZED`. The pole's `occupied_space_inches` falls by the abandoned attachment's `allotted_space_inches`, releasing that space for reuse.

### 3.6. Field Audits and Unauthorized Attachments

During field audits a `FieldAuditor` logs unauthorized attachments — equipment found on a pole without a granted permit. Logging a finding captures the `pole_id`, the responsible `attacher_id`, the `discovered_space_inches` the attachment occupies and its `discovered_position_inches` above ground (both greater than zero), a `good_faith` flag, and an `estimated_install_years_ago` count (at least 1) estimating how long the attachment has been in place. The finding records the auditor's `X-User-ID` as `auditor_user_id`, stamps `audited_at` from the clock, and enters state `FLAGGED`.

Creation immediately prices the exposure. The annual line is the owner's `annual_rental_rate_cents` multiplied by `discovered_space_inches`, divided by twelve, and rounded half-up. The `penalty_cents` follows a size tier: it is 25,000 cents when `discovered_space_inches` is twelve inches or fewer, and 50,000 cents when it exceeds twelve inches. The `back_rental_cents` is dual-variant on `good_faith`: a good-faith finding (`good_faith` true) is charged exactly one year of the annual line; a bad-faith finding (`good_faith` false) is charged the annual line multiplied by the smaller of `estimated_install_years_ago` and five years, capping multi-year exposure at five years. An `UNAUTHORIZED` invoice is then issued for the sum of `penalty_cents` and `back_rental_cents`, and its id is recorded on the finding as `penalty_invoice_id`.

A `JointUseCoordinator` resolves a finding by supplying a `resolution`. A removal moves the finding to `REMOVED`, from either `FLAGGED` or `DISPUTED`, with no space effect. A legalization moves the finding to `LEGALIZED`, again from either `FLAGGED` or `DISPUTED`, and is gated by two conditions: the pole must be `ACTIVE`, or `ERR_POLE_NOT_ACTIVE`; and the `discovered_space_inches` must fit within the pole's `usable_communication_space_inches` less `occupied_space_inches` and less `reserved_space_inches`, or `ERR_INSUFFICIENT_POLE_SPACE`. A legalization creates an `Attachment` in `ACTIVE` with `authorized` set to false, `allotted_space_inches` equal to `discovered_space_inches`, `position_inches` equal to `discovered_position_inches`, and `attacher_id` equal to the finding's attacher; the finding's `resulting_attachment_id` is set to the new attachment, and the pole's `occupied_space_inches` rises by the discovered space. (Disputing a finding, which drives `FLAGGED → DISPUTED`, is covered in §3.8.)

### 3.7. Invoicing, Rental True-Ups, and Payment

Beyond the make-ready and first-year rental invoices raised automatically during permitting, and the unauthorized invoices raised at findings, a `JointUseCoordinator` may generate an annual rental true-up. This invoice is created for a given `attacher_id`, a `pole_owner_id` giving the owner context, and an `invoice_type` of `ANNUAL_RENTAL`. Its amount aggregates the attacher's currently `ACTIVE` attachments that sit on poles owned by that `pole_owner_id`. The candidate attachments are ordered by `created_at` ascending. For each candidate, a per-line amount is computed as the owner's `annual_rental_rate_cents` multiplied by that attachment's `allotted_space_inches`, divided by twelve, and rounded half-up to whole cents. The invoice's `amount_cents` is the sum of those already-rounded per-line amounts — rounding is applied to each line before summation, which can differ from rounding a single grand total. The `line_items` array records one row per candidate, each row carrying a `label`, the `attachment_id`, and that line's `amount_cents`.

Every invoice, regardless of origin, records the billed `attacher_id`, an `application_id` for make-ready and first-year rental invoices (null otherwise), a `finding_id` for unauthorized invoices (null otherwise), and a `pole_owner_id` owner context for annual-rental true-ups (null otherwise). On issuance it enters `ISSUED`, stamps `issued_at` from the clock, and sets `due_at` to thirty days after issuance. As described in §2.9, an `ISSUED` invoice whose `due_at` has passed transitions to `OVERDUE` when the clock advances.

The owning `Attacher` pays an invoice, moving it to `PAID` from either `ISSUED` or `OVERDUE`. Payment requires ownership, or `ERR_UNAUTHORIZED`, and that no non-terminal dispute — one in `OPEN`, `UNDER_REVIEW`, or `INFO_REQUESTED` — currently references the invoice, or the payment is blocked with `ERR_INVOICE_UNDER_DISPUTE`. An attempt to pay an invoice already `PAID` or `VOID` is rejected with `ERR_INVOICE_ALREADY_TERMINAL`. On payment the attacher's `account_balance_cents` falls by the invoice's `amount_cents`, since the invoice leaves the outstanding set. A `JointUseCoordinator` may instead void an invoice, moving it to `VOID` from `ISSUED` or `OVERDUE`, likewise lowering the attacher's `account_balance_cents`.

### 3.8. Disputes

An `Attacher` may open a dispute against a billing or an audit. Opening a dispute names the disputing `attacher_id`, a free-text `reason`, and exactly one subject: either an `invoice_id` or a `finding_id`, but never both and never neither — supplying zero or two subjects is rejected with `ERR_DISPUTE_SUBJECT_INVALID`. A new dispute enters `OPEN` with `round_count` at zero, and if it names a `finding_id` the referenced finding is driven `FLAGGED → DISPUTED`.

Disputes advance through a transition endpoint that carries a `to_state`. A `JointUseCoordinator` opens review, moving the dispute `OPEN → UNDER_REVIEW`, and may ask the attacher for more information, moving it `UNDER_REVIEW → INFO_REQUESTED`. The owning `Attacher` responds, moving it `INFO_REQUESTED → UNDER_REVIEW`; each such response is one completed negotiation cycle and increments `round_count` by one. This `UNDER_REVIEW ↔ INFO_REQUESTED` loop may repeat any number of rounds. A response by anyone other than the owning attacher is `ERR_UNAUTHORIZED`.

From `UNDER_REVIEW`, a `JointUseCoordinator` resolves the dispute. An uphold moves it `UNDER_REVIEW → RESOLVED_UPHELD`, sets `resolution` to `UPHELD`, and leaves the disputed invoice or finding unchanged. An adjustment moves it `UNDER_REVIEW → RESOLVED_ADJUSTED` and requires a monetary correction: the dispute must reference an invoice whose `status` is `ISSUED` or `OVERDUE`, else `ERR_INVALID_STATE`, and a non-negative `adjusted_amount_cents` must be supplied, else `ERR_VALIDATION`. An adjustment sets `resolution` to `ADJUSTED`, cascades by replacing the referenced invoice's `amount_cents` with the `adjusted_amount_cents`, and recomputes the attacher's `account_balance_cents` from the new invoice amount. The owning `Attacher` may instead withdraw a dispute, moving it to `WITHDRAWN` from `OPEN`, `UNDER_REVIEW`, or `INFO_REQUESTED`, subject to the ownership check.

### 3.9. Retiring Poles

When a pole leaves service, a `JointUseCoordinator` retires it, moving it `ACTIVE → RETIRED`. Retirement is allowed only when the pole is entirely clear: its `occupied_space_inches` and its `reserved_space_inches` must both be zero, and no application on that pole may sit in a non-terminal status — none in `SUBMITTED`, `SURVEYED`, `ESTIMATE_ISSUED`, or `ESTIMATE_ACCEPTED`. If any attachment, reservation, or open application remains, retirement is rejected with `ERR_POLE_HAS_ATTACHMENTS`. A `RETIRED` pole is terminal, and any operation that requires an `ACTIVE` pole — a survey or a finding legalization — will thereafter fail with `ERR_POLE_NOT_ACTIVE`.

## 4. Endpoint Definitions

Operations that register a new, stand-alone resource return `201 Created`; this includes registering owners, crews, poles, and attachers, submitting an application, submitting a survey, logging a finding, generating a rental invoice, and opening a dispute. Operations that modify an existing resource — every state transition, decision, payment, and the logical-clock control — return `200 OK`. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/joint-use/pole-owners` | Register a pole owner | JointUseCoordinator |
| GET | `/joint-use/pole-owners/{ownerId}` | Get a pole owner | JointUseCoordinator, Engineer, PermitOfficer, FieldAuditor, Attacher |
| POST | `/joint-use/crews` | Register a make-ready crew | JointUseCoordinator |
| GET | `/joint-use/crews` | List crews (filter by owner) | JointUseCoordinator, Engineer |
| GET | `/joint-use/crews/{crewId}` | Get a crew | JointUseCoordinator, Engineer |
| POST | `/joint-use/poles` | Register a pole | JointUseCoordinator |
| GET | `/joint-use/poles` | List poles (filter by owner) | JointUseCoordinator, Engineer, PermitOfficer, FieldAuditor, Attacher |
| GET | `/joint-use/poles/{poleId}` | Get a pole (incl. occupied/reserved space) | JointUseCoordinator, Engineer, PermitOfficer, FieldAuditor, Attacher |
| POST | `/joint-use/poles/{poleId}/retire` | Retire a pole with no attachments, reservations, or open applications | JointUseCoordinator |
| POST | `/joint-use/attachers` | Register an attacher | JointUseCoordinator |
| GET | `/joint-use/attachers/{attacherId}` | Get an attacher (incl. account balance) | JointUseCoordinator, Engineer, PermitOfficer, FieldAuditor, Attacher |
| POST | `/joint-use/applications` | Submit an attachment application | Attacher |
| GET | `/joint-use/applications` | List applications (filter by pole/attacher) | JointUseCoordinator, Engineer, PermitOfficer, Attacher |
| GET | `/joint-use/applications/{appId}` | Get an application | JointUseCoordinator, Engineer, PermitOfficer, Attacher |
| POST | `/joint-use/applications/{appId}/survey` | Submit the make-ready survey | Engineer |
| POST | `/joint-use/applications/{appId}/estimate` | Issue or re-issue the engineering estimate | Engineer |
| POST | `/joint-use/applications/{appId}/estimate-decision` | Accept or reject the estimate | Attacher |
| POST | `/joint-use/applications/{appId}/permit` | Grant or deny the permit | PermitOfficer |
| POST | `/joint-use/applications/{appId}/withdraw` | Withdraw a non-terminal application | Attacher |
| GET | `/joint-use/surveys` | List surveys (filter by application/crew) | JointUseCoordinator, Engineer |
| GET | `/joint-use/surveys/{surveyId}` | Get a survey | JointUseCoordinator, Engineer |
| GET | `/joint-use/attachments` | List attachments (filter by pole/attacher/application) | JointUseCoordinator, Engineer, PermitOfficer, FieldAuditor, Attacher |
| GET | `/joint-use/attachments/{attId}` | Get an attachment | JointUseCoordinator, Engineer, PermitOfficer, FieldAuditor, Attacher |
| POST | `/joint-use/attachments/{attId}/transfer` | Transfer an attachment to another attacher | Attacher |
| POST | `/joint-use/attachments/{attId}/abandon` | Abandon an attachment | Attacher |
| POST | `/joint-use/findings` | Log an unauthorized-attachment finding | FieldAuditor |
| GET | `/joint-use/findings` | List findings (filter by pole/attacher) | JointUseCoordinator, FieldAuditor, Attacher |
| GET | `/joint-use/findings/{findingId}` | Get a finding | JointUseCoordinator, FieldAuditor, Attacher |
| POST | `/joint-use/findings/{findingId}/resolve` | Legalize or remove a flagged/disputed finding | JointUseCoordinator |
| POST | `/joint-use/invoices` | Generate an annual-rental true-up invoice | JointUseCoordinator |
| GET | `/joint-use/invoices` | List invoices (filter by attacher/owner/application/finding) | JointUseCoordinator, Attacher |
| GET | `/joint-use/invoices/{invoiceId}` | Get an invoice | JointUseCoordinator, Attacher |
| POST | `/joint-use/invoices/{invoiceId}/pay` | Pay an invoice | Attacher |
| POST | `/joint-use/invoices/{invoiceId}/void` | Void an invoice | JointUseCoordinator |
| POST | `/joint-use/disputes` | Open a dispute over an invoice or a finding | Attacher |
| GET | `/joint-use/disputes` | List disputes (filter by attacher/invoice/finding) | JointUseCoordinator, Attacher |
| GET | `/joint-use/disputes/{disputeId}` | Get a dispute | JointUseCoordinator, Attacher |
| POST | `/joint-use/disputes/{disputeId}/transition` | Advance a dispute (review, request-info, respond, resolve, withdraw) | Attacher, JointUseCoordinator |
| POST | `/_clock/set_current_utc` | Set the logical clock | JointUseCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_POLE_OWNER_NOT_FOUND` | 404 |
| `ERR_CREW_NOT_FOUND` | 404 |
| `ERR_POLE_NOT_FOUND` | 404 |
| `ERR_ATTACHER_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_SURVEY_NOT_FOUND` | 404 |
| `ERR_ATTACHMENT_NOT_FOUND` | 404 |
| `ERR_FINDING_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_DISPUTE_NOT_FOUND` | 404 |
| `ERR_DUPLICATE_CIN` | 409 |
| `ERR_DUPLICATE_POLE_TAG` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ESTIMATE_EXPIRED` | 409 |
| `ERR_POLE_NOT_ACTIVE` | 409 |
| `ERR_POLE_HAS_ATTACHMENTS` | 409 |
| `ERR_INVOICE_UNDER_DISPUTE` | 409 |
| `ERR_INVOICE_ALREADY_TERMINAL` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_CREW_DOUBLE_BOOKED` | 409 |
| `ERR_CLEARANCE_VIOLATION` | 409 |
| `ERR_INSUFFICIENT_POLE_SPACE` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_DISPUTE_SUBJECT_INVALID` | 422 |
</content>
</invoke>
