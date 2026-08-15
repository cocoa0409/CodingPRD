# Insurance Cancellation & Nonrenewal Compliance API — Product Requirements Document

## 1. Introduction

Mid-term cancellation and nonrenewal are among the most heavily regulated actions a carrier can take against an in-force policy. Every state publishes its own catalogue of permissible cancellation grounds, its own advance-notice minima owed to policyholders and to mortgagee or lienholder interests, its own rules governing how much unearned premium may be withheld when the insured asks to cancel, and its own deadlines and mandatory content for nonrenewal notices. A carrier that mails a notice one day late, refunds a cent too little, or cannot evidence proof of mailing invites rescinded cancellations, disputed lapses, and regulatory censure. This document specifies an insurer policy-services API that makes those statutory rules executable: ground validation against state filing profiles, notice-period calculation with proof-of-mailing records, pro-rata versus short-rate premium return, reinstatement windows and their fees, third-party interest notification, appeal and rescission-of-cancellation handling, and regulatory reporting on cancellation and nonrenewal volumes.

The API is mounted under `/carrier` and serves three operator roles — compliance officers, underwriters, and policyholders — under a segregation-of-duties model in which the operator who opens a case may never be the operator who approves it. Time is a first-class input rather than an accident of the wall clock: the server maintains a logical clock whose advances drive the scheduled sweeps that make cancellations effective, expire nonrenewed policies, close stale reinstatement windows, and flag hardened coverage lapses. Every monetary figure is an integer number of cents and every statutory interval is counted in whole days; the global conventions come first in §2, and the workflows that depend on them follow in §3.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting operator and `X-User-Role` to specify their operational capacity. A request in which either header is missing or malformed is rejected with `ERR_MISSING_AUTH_CONTEXT`. The system recognizes exactly three roles, spelled precisely as follows: `ComplianceOfficer`, `Underwriter`, and `Policyholder`. Access to every endpoint is restricted by role, and an attempt to perform an operation outside the caller's designated role is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

A `ComplianceOfficer` is the carrier's compliance function: this role authors and activates state filing profiles, approves cancellations, nonrenewals, and reinstatement requests, rescinds cases, accepts and decides appeals, finalizes regulatory reports, and drives the logical clock. It is deliberately segregated from case creation. An `Underwriter` runs the book of business: issuing policies, opening cancellation and nonrenewal cases, dispatching statutory notices, maintaining notice delivery status, and filing appeals on behalf of mortgagees. A `Policyholder` is the named insured: this role requests insured-initiated cancellation, submits reinstatement requests, and files its own appeals.

Role identity binds to data differently per role. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, to enforce segregation-of-duties comparisons) but never compares it to any entity's `id`. The same holds when `X-User-Role` is `Underwriter`: an opaque operator identifier, recorded where the workflow requires it, but never matched against a stored entity. When `X-User-Role` is `Policyholder`, `X-User-ID` is the `id` of the acting Policyholder; ownership checks on any resource that references a Policyholder compare the resource's foreign-key field — such as a policy's `policyholder_id` — to `X-User-ID`, so a policyholder can act only on its own policies.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it may never be less than 1 or greater than 100. The `offset` parameter states how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

List endpoints also accept optional equality filters drawn from the resource's own fields. Filing profiles filter by `state_code` and `status`; policies by `policyholder_id`, `state_profile_id`, and `status`; cancellation cases and nonrenewal cases by `policy_id` and `status`; notices by `cancellation_case_id`, `nonrenewal_case_id`, `insured_interest_id`, and `status`; reinstatement requests by `policy_id`, `cancellation_case_id`, and `status`; appeals by `cancellation_case_id`, `policy_id`, and `status`; and regulatory reports by `state_profile_id`, `report_period`, and `status`.

### 2.4. The Logical Clock and Scheduled Compliance Sweeps

Every temporal rule in this API is evaluated against a server-maintained logical clock, never against wall-clock time. Before any operator intervention the logical clock reads exactly 2026-08-01T00:00:00Z, and it moves only when a `ComplianceOfficer` invokes the clock-setting capability with a `to_iso8601` instant; the response echoes the new `current_utc`, and the clock never falls back to wall-clock time on its own. Wherever this document says "the current clock date", it means the calendar date of that logical instant.

Advancing the clock is what makes time-borne rules execute. Each advance runs four scheduled sweeps in its wake: the cancellation effectiveness sweep, which moves eligible policies from `CANCEL_PENDING` to `CANCELLED`; the policy expiry sweep, which moves nonrenewed policies from `NONRENEWAL_PENDING` to `EXPIRED`; the reinstatement expiry sweep, which retires reinstatement requests whose windows have closed; and the lapse sweep, which recomputes the `lapse_flag` on cancelled policies. The gate conditions for each sweep live with their workflows in §3.

### 2.5. Common Resource Properties

All primary resources — filing profiles, policyholders, policies, insured interests, cancellation cases, nonrenewal cases, notices, reinstatement requests, appeals, and regulatory reports — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed counter that increments by one on every mutation of the resource.

Cascading changes count as mutations. When a workflow moves a policy between statuses, increments its `reinstatements_used`, stamps or clears its `cancellation_effective_date`, or flips its `lapse_flag`, the policy's `updated_at` is refreshed and its `version` is incremented. The premium ledger is the one exception to the common-fields convention: a PremiumLedgerEntry is immutable once posted, carries only `id` and `created_at`, and has neither `updated_at` nor `version`.

### 2.6. Date Arithmetic and Monetary Precision

Two calendars and one currency govern every figure the API produces. All business dates — term boundaries, mailing dates, deadlines, effective dates — are ISO 8601 calendar dates in `YYYY-MM-DD` form, and every interval between them is counted in whole days with no time-of-day component, so a deadline measured in days always lands on a whole calendar date. Calendar months, such as a report's `report_period`, use `YYYY-MM` form.

Money is always an integer number of cents; fields such as `total_premium_cents`, `return_premium_cents`, `amount_cents`, and `reinstatement_fee_cents` never carry fractional cents. Where a computation produces a fraction, the result is rounded half-up to a whole cent. Premium-return arithmetic rounds twice, in a pinned order — once when the unearned premium is produced and again after any short-rate penalty is applied — and §3.4 fixes that order as mandatory.

### 2.7. Nested Resource Retrieval

The API enforces strict left-to-right validation on every path that nests one resource beneath another. When a path contains several identifiers — a policy and the interests listed beneath it, for example — the server resolves each identifier in turn, and the first identifier that does not resolve to an existing resource rejects the request immediately with `ERR_NOT_FOUND`; later identifiers in the path are never consulted once an earlier one fails. This ordering applies equally to reads and to nested creation, so an interest can never be attached beneath a policy that does not exist.

### 2.8. Optimistic Concurrency Control

Two write operations carry an optimistic concurrency guard, and both name the same field. Opening a cancellation case and submitting a reinstatement request each require the caller to supply `expected_policy_version`, holding the `version` of the target Policy as the client last observed it. If the supplied value does not equal the policy's current `version` at write time, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

The guard exists because both workflows make decisions that are only sound against a fresh view of the policy. When a cancellation case is opened, the open-case exclusivity check would otherwise run against obsolete data if another writer had advanced the policy since the client read it. When a reinstatement request is submitted, another writer may have just submitted a reinstatement request of its own — one that, once approved, would consume one of the policy's limited reinstatement slots — leaving the current writer's view of the policy stale. In both cases the stale write is refused rather than allowed to proceed on an outdated snapshot. Endpoints not named here take no version field at all. Note that this check is the final tier of the validation order in §2.11, so a request that fails an earlier rule reports that rule's error rather than a stale-version rejection.

### 2.9. The Premium Ledger

Every premium movement on a policy is recorded as an append-only PremiumLedgerEntry. A ledger line carries the `policy_id` it belongs to, an `entry_kind`, a signed `amount_cents` — positive when premium is written or a fee is charged, negative when money is refunded to the insured — the `effective_date` the entry applies to, and, for return entries, the `cancellation_case_id` of the originating cancellation case (unset otherwise). Five entry kinds exist: `WRITTEN`, `RETURN_PRO_RATA`, `RETURN_SHORT_RATE`, `LAPSE_FEE`, and `REINSTATEMENT_FEE`.

Four posting events write ledger lines. Issuing a policy posts a `WRITTEN` entry for the full `total_premium_cents`. A cancellation that reaches effectiveness posts a `RETURN_PRO_RATA` or `RETURN_SHORT_RATE` entry — chosen by the case's pinned `return_method` — with a negative amount equal to the finalized `return_premium_cents`. An approved reinstatement posts a positive `REINSTATEMENT_FEE` entry for the request's computed `reinstatement_fee_cents`. An appeal that overturns an already-effective cancellation posts a compensating `RETURN_PRO_RATA` entry with a positive amount exactly equal to the original negative return entry. The ledger for a policy can be listed chronologically, ordered by `effective_date` with ties broken by `created_at`, and the lines posted by a single cancellation case can be listed on their own.

### 2.10. Regulatory Volume Reporting

Volume reporting is driven by the same cascades that move cases, never by operator data entry. A RegulatoryReport is keyed by a `state_profile_id` and a `report_period` — a calendar month in `YYYY-MM` form — and accumulates three counters. The `nonrenewal_count` counts nonrenewal cases that reached `COMPLETED` against policies pinned to that profile whose `term_end_date` falls within the period. The `cancellation_count` counts cancellation cases that reached `EFFECTIVE` against policies pinned to that profile whose `scheduled_effective_date` falls within the period. The `rescinded_count` counts cancellation and nonrenewal cases whose rescission falls within the period. A period runs from the first day of its month, inclusive, up to the first day of the following month, exclusive — a left-closed, right-open window — and counting is order-insensitive.

Report rows are never created by hand. The first cascade that touches a profile-and-month pair auto-creates the row in `OPEN` status and increments the appropriate counter; later cascades increment the same row. A `ComplianceOfficer` finalizes an `OPEN` report only after its period has fully closed — the current clock month must be later than the `report_period`, and a finalize attempted while the clock is still within the period is rejected with `ERR_REPORT_PERIOD_STILL_OPEN`. `FINALIZED` is terminal. Reports are readable by `ComplianceOfficer` and `Underwriter` operators.

### 2.11. Validation Order and Error Precedence

Every request passes through the same ordered gauntlet, and a failure at any tier masks every later tier. The tiers, evaluated in this order, are:

1. Authentication context: the `X-User-ID` and `X-User-Role` headers must be present and well-formed (`ERR_MISSING_AUTH_CONTEXT`).
2. Authorization: the caller's role must be admitted to the endpoint (`ERR_FORBIDDEN_FOR_ROLE`).
3. Existence: path identifiers must resolve, validated left-to-right (`ERR_NOT_FOUND`).
4. State admissibility: the target resource must be in a state that admits the requested transition (`ERR_INVALID_STATE`).
5. Segregation of duties on approval and decision endpoints: the approver's or decider's `X-User-ID` must differ from the `X-User-ID` that performed the preceding workflow step (`ERR_SEGREGATION_OF_DUTIES`).
6. Statutory ground permissibility when a cancellation is opened (`ERR_GROUND_NOT_PERMITTED_IN_STATE`).
7. Notice-set completeness and statutory mailing windows on notice dispatch (`ERR_NOTICE_SET_INCOMPLETE`, `ERR_NOTICE_PERIOD_SHORTFALL`, `ERR_NONRENEWAL_NOTICE_LATE`, `ERR_MAILING_DATE_IN_FUTURE`).
8. Temporal boundaries: scheduled dates no earlier than their statutory floors, nonrenewals opened on or before their deadline, reinstatements inside their window (`ERR_EFFECTIVE_DATE_TOO_EARLY`, `ERR_NONRENEWAL_DEADLINE_PASSED`, `ERR_REINSTATEMENT_WINDOW_CLOSED`).
9. Uniqueness: one open cancellation case per policy, one open nonrenewal case per policy, one `ACTIVE` profile per `state_code`, and globally unique policy numbers (`ERR_CANCELLATION_ALREADY_OPEN`, `ERR_NONRENEWAL_ALREADY_OPEN`, `ERR_STATE_PROFILE_CONFLICT`, `ERR_DUPLICATE_POLICY_NUMBER`).
10. Referential coherence: an interest referenced by a notice must belong to the case's policy, an issuing profile must be `ACTIVE`, and a retire target must be unreferenced by live policies (`ERR_INTEREST_POLICY_MISMATCH`, `ERR_STATE_PROFILE_IN_USE`, `ERR_INVALID_REQUEST`).
11. Optimistic concurrency: `expected_policy_version` must equal the policy's current `version` (`ERR_STALE_VERSION`).

## 3. Business Logic & Workflows

### 3.1. State Filing Profiles: The Statutory Baseline

Before any policy can be issued, a `ComplianceOfficer` codifies a state's statute into a StateFilingProfile. Creation captures the two-letter `state_code`; the `permissible_grounds` the state allows mid-term, a subset of `NONPAYMENT`, `MATERIAL_MISREPRESENTATION`, `SUBSTANTIAL_CHANGE_IN_RISK`, and `LICENSE_SUSPENSION`; the statutory notice minima `nonpayment_notice_days`, `other_grounds_notice_days`, `mortgagee_notice_days`, and `nonrenewal_notice_days`; the `short_rate_penalty_pct`, the penalty fraction withheld from unearned premium when the insured requests cancellation — a value of 0.0 makes pro-rata return mandatory in that state; the `reinstatement_window_days` and `max_reinstatements` that bound post-cancellation revival; the `nonrenewal_content_codes` every nonrenewal notice must carry, a subset of `SPECIFIC_REASON`, `LOSS_HISTORY_SUMMARY`, `FAIR_PLAN_INFO`, and `APPEAL_RIGHTS`; and an optional `version_note` filing reference that defaults to empty. A new profile is born `DRAFT`.

Activation moves a profile `DRAFT → ACTIVE`, and only `ACTIVE` profiles are consulted by calculations. At most one profile per `state_code` may be `ACTIVE` at any moment: activating a profile while another `ACTIVE` profile carries the same code is rejected with `ERR_STATE_PROFILE_CONFLICT`. Retirement moves a profile `ACTIVE → RETIRED`, but only once no policy in `ACTIVE`, `CANCEL_PENDING`, or `NONRENEWAL_PENDING` status still references it — a retire attempted while such live policies exist is rejected with `ERR_STATE_PROFILE_IN_USE`. `RETIRED` is terminal.

### 3.2. Policyholders, Policy Issuance, and Insured Interests

An `Underwriter` onboards the book of business. A Policyholder record captures the insured's `full_name`, the `mailing_address` used for proof-of-mailing notices, and a contact `email`. Policy issuance then binds a policyholder to a filing profile: the request carries the `policyholder_id`, the `state_profile_id` of the governing profile — pinned at issuance for the life of the policy — a carrier-visible `policy_number` that must be globally unique across all policies, the `term_start_date` and `term_end_date`, and the `total_premium_cents` written for the full term. A duplicate `policy_number` is rejected with `ERR_DUPLICATE_POLICY_NUMBER`. Issuance against a profile that is not `ACTIVE`, a `term_end_date` that does not fall strictly after the `term_start_date`, a non-positive premium, or any missing or invalid field is rejected as malformed with `ERR_INVALID_REQUEST`.

A newly issued policy is `ACTIVE`, with `reinstatements_used` at zero, `cancellation_effective_date` unset, and `lapse_flag` false; issuance also posts the policy's first ledger line, a `WRITTEN` entry for the full premium. While the policy is on the books, the `Underwriter` may attach insured interests to it — each recording an `interest_type` of `MORTGAGEE`, `LIENHOLDER`, or `ADDITIONAL_INTEREST`, the `institution_name`, a notice `mailing_address`, and an optional external `loan_number` that defaults to empty. Every attached interest is owed statutory notice of any later cancellation or nonrenewal, which is why the dispatch machinery of §3.4 counts them so carefully.

### 3.3. Opening a Cancellation Case

Either an `Underwriter` or the `Policyholder` may open a cancellation case, but the ground chooses the actor. A `ground_code` of `INSURED_REQUEST` may be submitted only by the `Policyholder`; the insurer-initiated grounds — `NONPAYMENT`, `MATERIAL_MISREPRESENTATION`, `SUBSTANTIAL_CHANGE_IN_RISK`, and `LICENSE_SUSPENSION` — may be submitted only by an `Underwriter`. Crossing that line is rejected with `ERR_GROUND_ROLE_MISMATCH`. Beyond the role check, the ground must be statutorily permitted: an insurer-initiated `ground_code` must appear in the pinned profile's `permissible_grounds`, while `INSURED_REQUEST` is always permitted; a ground the state does not allow mid-term is rejected with `ERR_GROUND_NOT_PERMITTED_IN_STATE`.

Two further guards protect the policy itself. The policy must be `ACTIVE` — opening a case against a policy in any other status fails with `ERR_POLICY_NOT_ACTIVE` — and at most one cancellation case may be open per policy at a time, where open means `DRAFT`, `PENDING_APPROVAL`, `APPROVED`, or `NOTICE_SENT`; a second open case is rejected with `ERR_CANCELLATION_ALREADY_OPEN`. Creation also carries the optimistic-concurrency guard of §2.8: the payload must include `expected_policy_version` equal to the policy's current `version`, or the request is rejected with `ERR_STALE_VERSION`.

A successfully opened case passes through its initial `DRAFT` status into `PENDING_APPROVAL`, records the `requested_on_date` as the current clock date and the `requested_by_role` as the caller's role, and bumps the policy's `version`. Creation immediately computes and pins two values that govern everything downstream. The first is `earliest_effective_date`, the statutory floor for the cancellation's effective date. The base tier is the profile's `nonpayment_notice_days` when the ground is `NONPAYMENT`, and the profile's `other_grounds_notice_days` for every other ground — including `INSURED_REQUEST`. When the policy carries at least one insured interest, each such interest is owed the profile's `mortgagee_notice_days`, and the floor becomes the `requested_on_date` plus the greater of the base tier and `mortgagee_notice_days`; with no interests on the policy, the floor is simply the `requested_on_date` plus the base tier. The second pinned value is the `return_method`, which selects how unearned premium will be returned when the case takes effect: `SHORT_RATE` applies only when the ground is `INSURED_REQUEST` and the profile's `short_rate_penalty_pct` is greater than zero; `PRO_RATA` applies to every insurer-initiated ground, and to insured-requested cancellations in states whose penalty fraction is 0.0.

### 3.4. Approval, Statutory Notices, and Cancellation Effectiveness

Approval belongs to a `ComplianceOfficer`, and two gates guard it. Segregation of duties comes first: the approving officer's `X-User-ID` must differ from the `X-User-ID` that created the case, or approval is refused with `ERR_SEGREGATION_OF_DUTIES`. The approval payload then supplies the `scheduled_effective_date`, which must be the same as or later than the case's `earliest_effective_date` — an earlier date is rejected with `ERR_EFFECTIVE_DATE_TOO_EARLY`, while scheduling exactly on the earliest date is permitted. Approval moves the case `PENDING_APPROVAL → APPROVED`, stores the scheduled date on the case, moves the policy `ACTIVE → CANCEL_PENDING`, and bumps the policy's `version`. Coverage continues uninterrupted until the scheduled date; the statutory notice window is now running.

With an approved case in hand, an `Underwriter` dispatches the full statutory notice set as a single `notices` payload. The set must contain exactly one notice addressed to the `POLICYHOLDER` plus exactly one notice per insured interest on the policy, each interest notice bearing a `recipient_kind` that matches that interest's `interest_type` — `MORTGAGEE`, `LIENHOLDER`, or `ADDITIONAL_INTEREST`; a missing policyholder notice or a missing per-interest notice fails with `ERR_NOTICE_SET_INCOMPLETE`. Every interest-addressed notice must name its `insured_interest_id`, and that interest must belong to the same policy as the case: a reference to another policy's interest fails with `ERR_INTEREST_POLICY_MISMATCH`, while an invalid `recipient_kind` and `insured_interest_id` combination — including an `insured_interest_id` on the policyholder notice, which carries none — is malformed and rejected with `ERR_INVALID_REQUEST`. Each entry also records the mail room's `mailed_on_date` and a `tracking_code`, the USPS certificate-of-mailing or certified-mail number that serves as proof of mailing.

Two calendar rules then vet every entry in the set. No `mailed_on_date` may lie later than the current clock date (`ERR_MAILING_DATE_IN_FUTURE`). And each notice must leave enough statutory runway: the interval from a notice's `mailed_on_date` to the `scheduled_effective_date` must be at least the days owed to that recipient — the applicable base tier for the policyholder notice, `mortgagee_notice_days` for each interest notice — or the dispatch fails with `ERR_NOTICE_PERIOD_SHORTFALL`. A successful dispatch creates one NoticeRecord per payload entry, each born `MAILED`, each serving exactly one case — a cancellation notice sets `cancellation_case_id` and leaves `nonrenewal_case_id` unset — and moves the case `APPROVED → NOTICE_SENT`.

Notice records live their own small lifecycle in the mail stream. From `MAILED`, an `Underwriter` can confirm delivery, moving the record to `DELIVERY_CONFIRMED`, or mark the piece `RETURNED_UNDELIVERABLE`; both outcomes are terminal. An undeliverable notice is not a clerical footnote: while any notice for a case is `QUEUED` or `RETURNED_UNDELIVERABLE`, the effectiveness sweep refuses to let the cancellation take effect, the blocked case is surfaced with `ERR_NOTICE_NOT_MAILED`, and the policy remains `CANCEL_PENDING` until a replacement notice has been dispatched and mailed.

Effectiveness itself is systemic, not manual. When the current clock date reaches the case's `scheduled_effective_date` with the case in `NOTICE_SENT` and every notice for the case in `MAILED` or `DELIVERY_CONFIRMED`, the clock sweep moves the case `NOTICE_SENT → EFFECTIVE` and the policy `CANCEL_PENDING → CANCELLED`, stamps the policy's `cancellation_effective_date` with the scheduled date, posts the return-premium ledger line, and increments the `cancellation_count` of the regulatory report for the pinned profile and the month containing the scheduled date — auto-creating the `OPEN` report row if none exists yet.

The refund posted at that moment is the case's finalized `return_premium_cents`, and its arithmetic is pinned. The term length is the whole-day count between the policy's `term_start_date` and `term_end_date`. The elapsed time is the whole-day count between the `term_start_date` and the `scheduled_effective_date`, clamped so it never falls below zero and never exceeds the term length. The unearned premium is the `total_premium_cents` multiplied by the share of the term remaining — term length minus elapsed days, divided by term length — rounded half-up to a whole cent. Under `PRO_RATA`, that unearned figure is the refund. Under `SHORT_RATE`, the unearned figure is multiplied by one minus the profile's `short_rate_penalty_pct`, and the product is rounded half-up to a whole cent a second time. The two roundings are mandatory and must occur in exactly this order — first the unearned premium, then the penalty; collapsing the arithmetic into a single rounding at the end is forbidden. Identical inputs under `SHORT_RATE` always yield a strictly smaller refund than under `PRO_RATA`, so the pinned `return_method` matters to the cent.

### 3.5. Withdrawal and Rescission of a Cancellation

Two off-ramps exist before a cancellation takes effect. Withdrawal is the requester's own retreat: while a case sits in `PENDING_APPROVAL`, the party that opened it may withdraw it, moving the case to `WITHDRAWN`. The actor's role must match the case's recorded `requested_by_role` — an underwriter-opened case may be withdrawn only by an `Underwriter`, a policyholder-opened case only by the `Policyholder` — or the attempt is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

Rescission is the compliance function's reversal. A `ComplianceOfficer` may rescind a case that is `APPROVED` or `NOTICE_SENT`, supplying a `reason` that is recorded on the case as its `rescinded_reason`; a case in any other status does not admit the transition and is rejected with `ERR_INVALID_STATE`. Once the case has reached `NOTICE_SENT`, the calendar binds as well: the current clock date must be strictly earlier than the `scheduled_effective_date`, because a rescission attempted on or after the cancellation's effective date is rejected with `ERR_ALREADY_EFFECTIVE`. Rescinding moves the case to `RESCINDED`, returns the policy from `CANCEL_PENDING` to `ACTIVE`, bumps the policy's `version`, and increments the `rescinded_count` on the regulatory report for the pinned profile and the current clock month — auto-creating an `OPEN` report row when none exists.

### 3.6. The Nonrenewal Path

Nonrenewal is the carrier's decision to let coverage run to its scheduled expiration without offering a renewal. An `Underwriter` opens a nonrenewal case with the `policy_id`, a `reason_code` of `UNDERWRITING_GUIDELINES`, `LOSS_HISTORY`, `CARRIER_WITHDRAWAL`, or `RISK_INELIGIBLE`, the specific `reason_text` that will appear on the notice, and the `content_codes_present` asserted for the notice. Three gates guard creation: the policy must be `ACTIVE` (`ERR_POLICY_NOT_ACTIVE`); no other nonrenewal case for the same policy may sit in `DRAFT`, `PENDING_APPROVAL`, `APPROVED`, or `NOTICE_SENT` (`ERR_NONRENEWAL_ALREADY_OPEN`); and the decision must come early enough — the current clock date must be on or before the policy's nonrenewal notice deadline, or the case is refused with `ERR_NONRENEWAL_DEADLINE_PASSED`. A case that passes moves from its initial `DRAFT` status into `PENDING_APPROVAL` with its `notice_deadline_date` computed and stored: the policy's `term_end_date` minus the pinned profile's `nonrenewal_notice_days`.

Approval mirrors the cancellation path with one statutory twist. A `ComplianceOfficer` approves the case, and segregation of duties applies — the approver's `X-User-ID` must differ from the creator's, or the approval fails with `ERR_SEGREGATION_OF_DUTIES`. The twist is content: the case's `content_codes_present` must cover every code in the pinned profile's `nonrenewal_content_codes`, and a notice program missing required content is rejected with `ERR_NONRENEWAL_CONTENT_INCOMPLETE`. Approval moves the case to `APPROVED`, stamps `decided_on_date` with the current clock date, moves the policy `ACTIVE → NONRENEWAL_PENDING` — coverage continues to the `term_end_date`, but no renewal offer will be made — and bumps the policy's `version`.

Notice dispatch again belongs to the `Underwriter` and again demands a complete set: exactly one notice addressed to the `POLICYHOLDER` plus exactly one notice per insured interest on the policy, with a missing piece failing as `ERR_NOTICE_SET_INCOMPLETE`. Each notice serves exactly one case — a nonrenewal notice sets `nonrenewal_case_id` and leaves `cancellation_case_id` unset — and carries the same `mailed_on_date` and `tracking_code` proof-of-mailing fields as a cancellation notice. The statutory clock differs from cancellation, though: every notice's `mailed_on_date` must be on or before the case's `notice_deadline_date`. Mailing exactly on the deadline is on time; mailing one day later is late, and a late set fails with `ERR_NONRENEWAL_NOTICE_LATE`. A successful dispatch creates the NoticeRecords in `MAILED` status and moves the case `APPROVED → NOTICE_SENT`.

A `ComplianceOfficer` may still rescind an `APPROVED` nonrenewal before notices go out, supplying a `reason`, moving the case to `RESCINDED`, returning the policy to `ACTIVE`, bumping its `version`, and incrementing the `rescinded_count` for the pinned profile and the current clock month. Past that point the expiry sweep takes over: when the current clock date reaches the policy's `term_end_date` with the case in `NOTICE_SENT`, the case moves `NOTICE_SENT → COMPLETED`, the policy moves `NONRENEWAL_PENDING → EXPIRED`, and the `nonrenewal_count` for the pinned profile and the month containing the `term_end_date` is incremented — auto-creating the `OPEN` report row if none exists.

### 3.7. Reinstatement After Cancellation

A cancelled policy is not necessarily dead. Within the pinned profile's `reinstatement_window_days`, measured from the policy's `cancellation_effective_date`, an `Underwriter` or the `Policyholder` may submit a reinstatement request naming the `policy_id`, the `cancellation_case_id` of the `EFFECTIVE` cancellation being reversed, and the concurrency guard `expected_policy_version` from §2.8 — a stale value is rejected with `ERR_STALE_VERSION`. Reinstatement exists only for policies in `CANCELLED` status; acting on a policy in any other status is rejected with `ERR_POLICY_NOT_CANCELLED`.

Submission stamps `submitted_on_date` with the current clock date and computes `lapse_days`, the whole-day count from the `cancellation_effective_date` to the submission date — zero when both are the same day. Eligibility is evaluated first: a `lapse_days` that exceeds the profile's `reinstatement_window_days` is rejected with `ERR_REINSTATEMENT_WINDOW_CLOSED`. Only then is the fee tiered, and the fee never feeds back into eligibility. A lapse of at most ten days carries no fee; a lapse of more than ten and at most thirty days carries a fee of 2,500 cents; a lapse of more than thirty days carries a fee of 5,000 cents. A lapse sitting exactly on a tier boundary falls into the lower tier — exactly ten days is free, exactly thirty days costs 2,500 cents. The computed amount is stored as `reinstatement_fee_cents`, the request lands in `SUBMITTED`, and the policy's `version` is bumped.

Approval is again segregated: the approving `ComplianceOfficer` must not be the operator who submitted the request (`ERR_SEGREGATION_OF_DUTIES`). Approval also re-verifies the policy's position — it must still be `CANCELLED` (`ERR_POLICY_NOT_CANCELLED`), and its `reinstatements_used` must still be below the pinned profile's `max_reinstatements`, since a policy that has exhausted its reinstatement slots fails with `ERR_REINSTATEMENT_LIMIT_REACHED`. An approved request moves `SUBMITTED → APPROVED`, returns the policy `CANCELLED → ACTIVE`, increments `reinstatements_used` by one, clears the `cancellation_effective_date` back to unset, posts a positive `REINSTATEMENT_FEE` ledger entry for the computed fee, and bumps the policy's `version`. The originating cancellation case deliberately stays `EFFECTIVE`, preserving the audit trail. A `ComplianceOfficer` may instead deny a `SUBMITTED` request, moving it to `DENIED`; both outcomes are terminal.

Two sweeps close the window from the system side. The reinstatement expiry sweep moves a `SUBMITTED` request to `EXPIRED` once the current clock date passes the policy's `cancellation_effective_date` plus the profile's `reinstatement_window_days`. Independently, the lapse sweep maintains the policy's `lapse_flag`: once more than thirty days have elapsed since the `cancellation_effective_date` without a reinstatement, the flag is set to true, marking the coverage lapse as hardened.

### 3.8. Appeals and the Overturn of a Cancellation

Both the insured and a mortgagee get a statutory voice after a cancellation has been noticed or has taken effect. Filing an appeal requires the linked cancellation case to be in `NOTICE_SENT` or `EFFECTIVE`; against a case in any other status the filing is rejected with `ERR_INVALID_STATE`. A `Policyholder` files with `filed_by` set to `POLICYHOLDER`, while an `Underwriter` files on a mortgagee's behalf with `filed_by` set to `MORTGAGEE`. The filing carries the `cancellation_case_id` and the appellant's `grounds_text`, and the new appeal lands in `FILED` with `filed_on_date` stamped from the clock and `decided_on_date` unset. The appeal also keeps a denormalized `policy_id` so that reporting queries need not walk back through the case.

Review is a two-officer process. A `ComplianceOfficer` first accepts the appeal, moving it `FILED → UNDER_REVIEW`. A decision then closes it: the deciding officer submits a `decision` of `UPHELD` or `OVERTURNED`, and segregation of duties forbids the accepting officer from also deciding — the decider's `X-User-ID` must differ from the accepter's, or the decision is rejected with `ERR_SEGREGATION_OF_DUTIES`. Either decision stamps `decided_on_date` with the current clock date, and both outcomes are terminal. An `UPHELD` outcome leaves the cancellation untouched. An `OVERTURNED` outcome unwinds an effective cancellation: when the linked case is `EFFECTIVE`, the case is moved to `RESCINDED`, the policy returns `CANCELLED → ACTIVE` with its `reinstatements_used` unchanged, a compensating ledger entry of kind `RETURN_PRO_RATA` is posted with a positive amount exactly equal to the original negative return entry, the `rescinded_count` for the pinned profile and the current clock month is incremented, and the policy's `version` is bumped.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources — filing profiles, policyholders, policies, insured interests, cancellation cases, nonrenewal cases, reinstatement requests, and appeals — return a `201 Created` status code. All other operations, including state-transition actions, notice dispatch, ledger and report reads, and the clock-setting capability, return a `200 OK` status code. The request and response shapes behind each endpoint are defined by the workflows in §3; the table below is the routing and authorization contract only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/carrier/_clock/set_current_utc` | Set the server's logical clock to an ISO-8601 UTC instant and run the scheduled sweeps | ComplianceOfficer |
| POST | `/carrier/state-profiles` | Create a StateFilingProfile (DRAFT) | ComplianceOfficer |
| GET | `/carrier/state-profiles/{profileId}` | Get a StateFilingProfile | ComplianceOfficer, Underwriter, Policyholder |
| GET | `/carrier/state-profiles` | List StateFilingProfiles | ComplianceOfficer, Underwriter, Policyholder |
| POST | `/carrier/state-profiles/{profileId}/activate` | Activate a DRAFT profile | ComplianceOfficer |
| POST | `/carrier/state-profiles/{profileId}/retire` | Retire an ACTIVE profile | ComplianceOfficer |
| POST | `/carrier/policyholders` | Create a Policyholder | Underwriter |
| GET | `/carrier/policyholders/{policyholderId}` | Get a Policyholder | ComplianceOfficer, Underwriter, Policyholder |
| POST | `/carrier/policies` | Issue a Policy (ACTIVE) against an ACTIVE profile | Underwriter |
| GET | `/carrier/policies/{policyId}` | Get a Policy | ComplianceOfficer, Underwriter, Policyholder |
| GET | `/carrier/policies` | List Policies | ComplianceOfficer, Underwriter, Policyholder |
| POST | `/carrier/policies/{policyId}/interests` | Attach a mortgagee / lienholder / additional interest | Underwriter |
| GET | `/carrier/policies/{id}/interests` | List interests on a policy | ComplianceOfficer, Underwriter, Policyholder |
| POST | `/carrier/cancellation-cases` | Open a CancellationCase (PENDING_APPROVAL) against an ACTIVE policy | Underwriter, Policyholder |
| GET | `/carrier/cancellation-cases/{caseId}` | Get a CancellationCase | ComplianceOfficer, Underwriter, Policyholder |
| GET | `/carrier/cancellation-cases` | List CancellationCases | ComplianceOfficer, Underwriter, Policyholder |
| POST | `/carrier/cancellation-cases/{caseId}/approve` | Approve a PENDING_APPROVAL cancellation (schedules the effective date) | ComplianceOfficer |
| POST | `/carrier/cancellation-cases/{caseId}/withdraw` | Withdraw a PENDING_APPROVAL case (requester role only) | Underwriter, Policyholder |
| POST | `/carrier/cancellation-cases/{caseId}/rescind` | Rescind an APPROVED or NOTICE_SENT cancellation before effectiveness | ComplianceOfficer |
| POST | `/carrier/cancellation-cases/{caseId}/dispatch-notices` | Dispatch the full statutory notice set for an APPROVED case | Underwriter |
| POST | `/carrier/nonrenewal-cases` | Open a NonrenewalCase (PENDING_APPROVAL) | Underwriter |
| GET | `/carrier/nonrenewal-cases/{caseId}` | Get a NonrenewalCase | ComplianceOfficer, Underwriter, Policyholder |
| GET | `/carrier/nonrenewal-cases` | List NonrenewalCases | ComplianceOfficer, Underwriter, Policyholder |
| POST | `/carrier/nonrenewal-cases/{caseId}/approve` | Approve a PENDING_APPROVAL nonrenewal | ComplianceOfficer |
| POST | `/carrier/nonrenewal-cases/{caseId}/rescind` | Rescind an APPROVED nonrenewal | ComplianceOfficer |
| POST | `/carrier/nonrenewal-cases/{caseId}/dispatch-notices` | Dispatch statutory nonrenewal notices | Underwriter |
| GET | `/carrier/notices/{noticeId}` | Get a NoticeRecord | ComplianceOfficer, Underwriter, Policyholder |
| GET | `/carrier/notices` | List NoticeRecords | ComplianceOfficer, Underwriter, Policyholder |
| POST | `/carrier/notices/{noticeId}/confirm-delivery` | Mark a MAILED notice DELIVERY_CONFIRMED | Underwriter |
| POST | `/carrier/notices/{noticeId}/mark-undeliverable` | Mark a MAILED notice RETURNED_UNDELIVERABLE | Underwriter |
| GET | `/carrier/cancellation-cases/{id}/ledger-entries` | List PremiumLedgerEntries posted by a specific cancellation case | ComplianceOfficer, Underwriter, Policyholder |
| GET | `/carrier/policies/{id}/ledger-entries` | List PremiumLedgerEntries for a policy (chronological by effective_date, then created_at) | ComplianceOfficer, Underwriter, Policyholder |
| POST | `/carrier/reinstatement-requests` | Submit a ReinstatementRequest for a CANCELLED policy | Underwriter, Policyholder |
| GET | `/carrier/reinstatement-requests/{requestId}` | Get a ReinstatementRequest | ComplianceOfficer, Underwriter, Policyholder |
| GET | `/carrier/reinstatement-requests` | List ReinstatementRequests | ComplianceOfficer, Underwriter, Policyholder |
| POST | `/carrier/reinstatement-requests/{requestId}/approve` | Approve a SUBMITTED reinstatement | ComplianceOfficer |
| POST | `/carrier/reinstatement-requests/{requestId}/deny` | Deny a SUBMITTED reinstatement | ComplianceOfficer |
| POST | `/carrier/appeals` | File an appeal against an EFFECTIVE or NOTICE_SENT cancellation | Policyholder, Underwriter |
| GET | `/carrier/appeals/{appealId}` | Get an AppealCase | ComplianceOfficer, Underwriter, Policyholder |
| GET | `/carrier/appeals` | List AppealCases | ComplianceOfficer, Underwriter, Policyholder |
| POST | `/carrier/appeals/{appealId}/accept-for-review` | Move a FILED appeal to UNDER_REVIEW | ComplianceOfficer |
| POST | `/carrier/appeals/{appealId}/decide` | Decide an UNDER_REVIEW appeal | ComplianceOfficer |
| GET | `/carrier/regulatory-reports` | List RegulatoryReports (auto-created OPEN by cascades) | ComplianceOfficer, Underwriter |
| GET | `/carrier/regulatory-reports/{reportId}` | Get a RegulatoryReport | ComplianceOfficer, Underwriter |
| POST | `/carrier/regulatory-reports/{reportId}/finalize` | Finalize an OPEN report after its period closes | ComplianceOfficer |

## 5. Error Code Catalogue

The trigger condition for each error is defined by the validation order in §2.11 and the workflow narratives in §3; this table is the identifier-to-status contract only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_CONTEXT` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_GROUND_ROLE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_GROUND_NOT_PERMITTED_IN_STATE` | 422 Unprocessable Entity |
| `ERR_POLICY_NOT_ACTIVE` | 409 Conflict |
| `ERR_POLICY_NOT_CANCELLED` | 409 Conflict |
| `ERR_CANCELLATION_ALREADY_OPEN` | 409 Conflict |
| `ERR_NONRENEWAL_ALREADY_OPEN` | 409 Conflict |
| `ERR_EFFECTIVE_DATE_TOO_EARLY` | 422 Unprocessable Entity |
| `ERR_NOTICE_SET_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_NOTICE_PERIOD_SHORTFALL` | 422 Unprocessable Entity |
| `ERR_MAILING_DATE_IN_FUTURE` | 422 Unprocessable Entity |
| `ERR_NOTICE_NOT_MAILED` | 409 Conflict |
| `ERR_NONRENEWAL_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_NONRENEWAL_CONTENT_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_NONRENEWAL_NOTICE_LATE` | 422 Unprocessable Entity |
| `ERR_REINSTATEMENT_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_REINSTATEMENT_LIMIT_REACHED` | 409 Conflict |
| `ERR_ALREADY_EFFECTIVE` | 409 Conflict |
| `ERR_STATE_PROFILE_CONFLICT` | 409 Conflict |
| `ERR_STATE_PROFILE_IN_USE` | 409 Conflict |
| `ERR_DUPLICATE_POLICY_NUMBER` | 409 Conflict |
| `ERR_INTEREST_POLICY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_REPORT_PERIOD_STILL_OPEN` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
