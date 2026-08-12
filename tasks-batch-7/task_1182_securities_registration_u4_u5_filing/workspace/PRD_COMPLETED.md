# Securities Registration & U4/U5 Filing API — Product Requirements Document

## 1. Introduction

The Securities Registration & U4/U5 Filing API powers the registration desk of a FINRA member firm. The desk shepherds each associated person through the full registration lifecycle: drafting the Form U4 with its jurisdiction and SRO selections, collecting fingerprints and background-disclosure answers, tracking qualification-exam obligations and sitting windows, and driving the request through compliance review to approval and activation. Once a person is registered, the desk stays busy — reportable events must be folded into U4 amendments inside a fixed statutory window, annual renewal invoices must be computed and collected, and any departure triggers a Form U5 whose wording is itself subject to consistency scrutiny. External regulators can open inquiries against any filing on the desk, and the firm must answer them on a clock.

This document defines the product requirements for that API. It is written for the engineers who will implement the service: all resources are mounted under the `/registration-desk` prefix, every workflow is described in business terms in Section 3, and the HTTP contract is summarized in Section 4. The desk is a compliance system first — segregation of duties between the person who files and the person who reviews, immutable audit-friendly state transitions, deadline arithmetic that a regulator could reproduce, and optimistic-concurrency guards on the two write paths where a stale view would do real damage.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that apply to every endpoint of the desk.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to declare the capacity in which they act. The desk recognizes exactly five roles, spelled exactly as follows: `RegistrationPrincipal`, `ComplianceOfficer`, `FinanceClerk`, `SystemOperator`, and `Regulator`. A request missing either header, or presenting a role outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not on the endpoint's authorized list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The role division reflects the desk's segregation-of-duties model. A `RegistrationPrincipal` runs the firm's filing side: onboarding applicants, drafting and submitting registration requests, managing jurisdiction selections, fingerprints, disclosures, exam windows, disclosure events, amendments, termination filings, and affiliation requests. A `ComplianceOfficer` is the independent reviewer: approving, returning, or denying registration requests, reviewing disclosure answers, waiving exam requirements, accepting or returning amendments, closing U5 filings, deciding affiliations, and answering regulatory inquiries — but never on a filing they themselves submitted. A `FinanceClerk` issues, collects, and voids renewal invoices. A `SystemOperator` administers the platform itself: onboarding and configuring firms, recording fingerprint outcomes and exam results, routing and closing inquiries, and driving the desk's logical clock. A `Regulator` is an external examiner who can open regulatory inquiries and otherwise reads.

For every one of these five roles — `RegistrationPrincipal`, `ComplianceOfficer`, `FinanceClerk`, `SystemOperator`, and `Regulator` alike — the `X-User-ID` header is an opaque operator identifier that is not tied to any persisted entity. The server may record it (for example, as the `submitter_user_id` stamped on a registration request at submission time, or as the value compared during segregation-of-duties checks), but it never compares `X-User-ID` against any entity's `id`.

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

Endpoints that return lists of resources paginate through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` below 1 or above 100, or a negative `offset` is rejected `ERR_INVALID_REQUEST` (400). Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order. List responses carry four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`. Where Section 4 advertises optional filters, the supported filter query parameters are exactly: registration-requests — `applicant_id`, `firm_id`, `status`; jurisdiction-selections — `registration_request_id`, `status`; fingerprint-submissions — `registration_request_id`, `status`; background-disclosures — `registration_request_id`, `review_status`; exam-requirements — `registration_request_id`, `status`, `exam_code`; exam-windows — `exam_requirement_id`, `status`; disclosure-events — `applicant_id`, `status`; amendment-filings — `disclosure_event_id`, `registration_request_id`, `status`; termination-filings — `registration_request_id`, `status`; u5-comments — `termination_filing_id`, `disposition`; affiliation-requests — `applicant_id`, `second_firm_id`, `first_registration_request_id`, `status`; renewal-invoices — `registration_request_id`, `status`, `cycle_year`; regulatory-inquiries — `firm_id`, `subject_filing_id`, `status`. Filters match on exact equality, a non-integer `cycle_year` filter is `ERR_INVALID_REQUEST`, and the firm and applicant lists take no filters.

### 2.4. Common Resource Properties

Every resource on the desk — Firm, IndividualApplicant, RegistrationRequest, JurisdictionSelection, FingerprintSubmission, BackgroundDisclosure, ExamRequirement, ExamWindow, DisclosureEvent, AmendmentFiling, TerminationFiling, U5Comment, AffiliationRequest, RenewalInvoice, and RegulatoryInquiry — carries the same set of system-managed properties:

- `id` (string): a server-minted UUID with no type prefix, assigned at creation.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that is assigned 1 at creation and increments by one on every mutation.

The notion of "mutation" is broad: explicit client edits, status transitions, server-side cascades that rewrite a row, and computed-field refreshes all update `updated_at` and increment `version` on the affected resource. Several write paths described below rely on `version` for optimistic concurrency control. Client-supplied date and timestamp values — `date_of_birth`, `event_date`, `termination_date`, `window_start`, and `window_end` — are stored and returned verbatim, exactly as supplied.

### 2.5. The Desk's Logical Clock

The desk runs on a logical server clock rather than wall-clock time. Before any operator intervenes, the clock reads exactly 2026-05-01T00:00:00Z — a fixed startup default — and it never silently falls back to wall-clock time. A `SystemOperator`-only capability sets the clock to the supplied instant passed as `to_iso8601` — the instant may be earlier or later than the current reading, and a missing or unparseable value is rejected `ERR_INVALID_REQUEST` (400); the response's `current_utc` echoes the supplied `to_iso8601` string verbatim. Setting the clock is not inert bookkeeping: each set evaluates the desk's time-based system transitions, first rolling approved registrations into active status when the calendar day turns and then sweeping exam credits whose validity has lapsed — activation is evaluated before expiry on the same set, so an exam credit whose registration activates at that moment is locked in and does not expire. Every temporal rule in this document — filing deadlines, exam sitting windows, credit expiry, response due dates, future-date prohibitions — is measured against this server clock.

### 2.6. Filing Deadlines: Calendar and Regulatory Bases

Three kinds of deadline share one computation, parameterized by the firm's configured deadline basis. A firm is created with the `CALENDAR` basis by default; a `SystemOperator` can switch the firm to the `REGULATORY` basis by patching the firm's `deadline_basis`, and the new basis applies prospectively to deadlines computed after the change — already-computed deadlines are not rewritten.

Under the `CALENDAR` basis, a deadline is the anchor instant plus the stated number of calendar days; weekends and holidays are ignored. Under the `REGULATORY` basis, the deadline is the anchor plus the stated number of business days: counting begins on the day after the anchor and advances day by day, counting only days that fall Monday through Friday (the system holiday calendar is empty, so only weekends are skipped). Whenever the window spanned by the count crosses at least one weekend, the regulatory basis lands on a date later than or equal to the one the calendar basis would produce for the same anchor and count. In either basis, the computed deadline is inclusive through the end of the returned day — 23:59:59.999Z.

The anchors and day counts are fixed by the filing type. A disclosure event's amendment deadline, `amendment_due_at`, is anchored on the event's `reported_at` and runs 30 days. A termination filing's `filing_deadline_at` is anchored on the `termination_date` and likewise runs 30 days. A regulatory inquiry's `response_due_at` is anchored on the inquiry's creation timestamp and runs 15 business days — inquiries always use the `REGULATORY` basis, regardless of the firm's configured basis.

### 2.7. Fees, Money, and Rounding

All money on the desk is represented as integer cents; there are no fractional-cent amounts anywhere in the API. Where a fee computation produces a component that needs rounding — the late surcharge on a renewal invoice being the one case — the component is rounded to whole cents using round-half-up before any summation takes place, and the components are summed only after each has been rounded. This per-component-then-sum convention is part of the fee contract described in Section 3.7.

### 2.8. Optimistic Concurrency Control

Two write paths on the desk are guarded by optimistic concurrency control, and exactly two — no other endpoint accepts a version field.

Paying a renewal invoice requires the request to carry `expected_renewal_invoice_version`, holding the invoice `version` the client last observed. If the invoice's current `version` has advanced past that value — because another writer has paid or voided it since — the payment is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a stale view of the invoice.

Patching a registration request requires the request body to carry `expected_registration_request_version`, holding the request `version` the client last observed. If the request's current `version` has advanced — because a system transition or another writer mutated it in the meantime — the patch is rejected with `ERR_STALE_VERSION` (HTTP 412).

On both guarded paths, omitting the expected-version field entirely is rejected `ERR_INVALID_REQUEST` (400); a value that is present but is not an integer equal to the resource's current `version` is `ERR_STALE_VERSION` (412).

### 2.9. Segregation of Duties

The desk forbids self-review. Six review actions require the acting `ComplianceOfficer`'s `X-User-ID` to differ from the `X-User-ID` recorded as the filer or submitter of the target: approving a registration request, returning it deficient, denying it, accepting an amendment filing, returning an amendment filing, and closing a termination filing. A violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Because `X-User-ID` is opaque (§2.1), the desk enforces this by remembering who filed: the submission path stamps `submitter_user_id` on the registration request, and filing paths record the filer's identifier for later comparison. The filer identifier recorded on an amendment filing or a termination filing is internal-only and is never serialized on those resources; by contrast, the registration request's `submitter_user_id` is part of the resource's serialized representation (null until the first submission).

### 2.10. Request Validation Order and Referential Integrity

Every incoming request passes through a fixed cascade of checks, and the ordering is part of the contract: when several problems exist at once, the check earliest in this order determines the error returned. The order is:

1. **Authentication** (every endpoint): both headers present and the role recognized — otherwise `ERR_UNAUTHENTICATED` (401).
2. **Role authorization** (every endpoint): the role is on the endpoint's authorized list — otherwise `ERR_FORBIDDEN_ROLE` (403).
3. **Existence** (every endpoint): every path identifier and every body foreign key must resolve to an existing entity. Resolution is validated left to right — path identifiers first, in path order, then body foreign keys in input order — and the first unresolvable reference yields `ERR_NOT_FOUND` (404).
4. **Uniqueness** (creation endpoints): a duplicate is rejected with `ERR_DUPLICATE` (409). The protected constraints are: `crd_number` unique across firms, `crd_number` unique across applicants, at most one renewal invoice per registration request and cycle year, at most one exam window in `SCHEDULED` or `OPEN` status per exam requirement, and at most one affiliation request in `PENDING` or `APPROVED` status per applicant and second firm.
5. **State legality** (all action endpoints): the target entity's current status must permit the requested transition, and terminal states accept no further transitions — otherwise `ERR_INVALID_STATE` (409).
6. **Optimistic concurrency** (invoice payment and registration-request patching only): the expected version must match — otherwise `ERR_STALE_VERSION` (412), per §2.8.
7. **Segregation of duties** (approve, return-deficient, deny, amendment accept, amendment return, and U5 close): self-review is rejected with `ERR_SEGREGATION_OF_DUTIES` (403), per §2.9.
8. **Regulatory gate** (registration-request approval): the exam, fingerprint, and disclosure preconditions of §3.5 must all hold — otherwise `ERR_REGULATORY_GATE` (422).
9. **Field shape** (every endpoint): required fields present, enum values inside their declared sets, minimum lengths honored (`explanation_text` at least 20 characters when the answer is yes; `narrative_text`, `inquiry_text`, and `response_text` at least 20 characters; `comment_text` at least 10 characters), `jurisdiction_code` matching the state-or-SRO pattern consistent with `jurisdiction_type`, and `window_end` strictly after `window_start` — otherwise `ERR_INVALID_REQUEST` (400).
10. **Temporal rules** (disclosure-event creation, termination-filing creation, exam-result recording, inquiry response): no future-dated `event_date` or `termination_date`, passing results inside their sitting window, and inquiry responses no later than their due date — otherwise `ERR_TEMPORAL_VIOLATION` (422).
11. **Cross-entity referential rules** (affiliation creation, amendment-filing creation, exam-window creation, jurisdiction-selection creation): the dual-registration, active-registration, SIE-prerequisite, and editable-parent rules of Section 3 — otherwise `ERR_REFERENTIAL_VIOLATION` (422).
12. **Fiscal rules** (renewal-invoice creation and payment): the registration is `ACTIVE`, the cycle is not already invoiced, and the payable amount is never negative — otherwise `ERR_FISCAL_VIOLATION` (422).

So, for example, an unauthenticated request that also carries a duplicate CRD number always surfaces `ERR_UNAUTHENTICATED`, and a payment carrying a stale version surfaces `ERR_STALE_VERSION` before any segregation or field-shape question is considered.

## 3. Business Logic & Workflows

### 3.1. Onboarding the Desk: Firms and Applicants

Before any filing exists, a `SystemOperator` onboards the member firm. Creating a firm requires its `crd_number` — the Central Registration Depository number, one to seven digits and unique across all firms, with duplicates rejected `ERR_DUPLICATE` — and its `legal_name` of one to 120 characters. A firm record is born with `status` `ACTIVE` (the lifecycle also defines `SUSPENDED`), a `deadline_basis` of `CALENDAR` — both fields serialized on every firm response — and an `open_inquiry_count` of zero; that count is computed, not stored input: it is the number of the firm's regulatory inquiries currently in `OPEN` or `PENDING_RESPONSE` status, recomputed on every inquiry status change.

Firm configuration can be revised after onboarding. A `SystemOperator` patching a firm may update its `legal_name`, flip its `status`, or — most consequentially — set the `deadline_basis` that governs every deadline the desk computes for the firm from that moment on (§2.6). Each successful patch increments the firm's `version`.

A `RegistrationPrincipal` onboards each person seeking registration as an individual applicant, supplying the applicant's own `crd_number` (again one to seven digits, unique across applicants), the `full_name` exactly as it will appear on the U4 (one to 120 characters), and a `date_of_birth` as an ISO `YYYY-MM-DD` date used for fingerprint identity matching. An applicant record exposes one computed flag, `fingerprint_required`: it is derived on read and is true whenever the applicant has no fingerprint submission in `CLEARED` status, false once one exists. Every applicant starts out needing fingerprints.

### 3.2. Drafting the U4: Requests, Jurisdictions, and Disclosure Answers

The registration request is the desk's central artifact — the machine-readable U4. A `RegistrationPrincipal` drafts one by naming the `applicant_id` of the person being registered, the `firm_id` of the sponsoring member firm, and the `registration_category` requested: `RR` for a registered representative, `IA` for an investment adviser, or `PRINCIPAL` for a principal. A new request enters `DRAFT` status with a `deficiency_count` of zero and no `submitted_at` or `approved_at` yet. While a request remains in `DRAFT` — or later in `DEFICIENT` — its `registration_category` may be amended; the patch is one of the desk's two OCC-guarded writes and must carry `expected_registration_request_version` matching the request's current `version` (§2.8), and each successful patch increments that `version`.

A draft U4 names the jurisdictions in which registration is sought. Each selection is created against a `registration_request_id` with a `jurisdiction_code` — either a two-letter uppercase state code or one of the SRO identifiers `FINRA`, `NYSE`, or `NASDAQ` — and a matching `jurisdiction_type` of `STATE` or `SRO`. Selections can only be added while the parent request is still editable, that is in `DRAFT` or `DEFICIENT`; attempting one against a request in any other status is rejected `ERR_REFERENTIAL_VIOLATION`. At selection time the row's `annual_fee_cents` is copied from the fee schedule: a `STATE` selection costs 5000 cents per year, while an `SRO` selection costs 0 cents because SRO coverage is folded into the firm's base renewal fee. Every selection starts in `SELECTED` status and from there follows the parent request's fate — approval flips each `SELECTED` row to `APPROVED`, denial flips them to `REJECTED`, and withdrawal flips them to `RELINQUISHED`.

The draft also carries the applicant's disclosure answers. Each background-disclosure row names its `registration_request_id`, the U4 `question_code` being answered — one of `CRIMINAL`, `REGULATORY`, `FINANCIAL`, `CIVIL`, or `EMPLOYMENT` — and the boolean `answer`, where true means the applicant answers YES and a reportable event exists. When `answer` is false the row needs nothing further; when `answer` is true the `explanation_text` is mandatory at no fewer than 20 characters, and a short or missing explanation is rejected `ERR_INVALID_REQUEST`. The explanation-length rule is enforced again at submission time, so a request cannot be submitted while any YES answer carries an inadequate explanation. Disclosure answers may be recorded against a request in any status; this creation path has no parent-state precondition.

Once a registration is `ACTIVE`, a `RegistrationPrincipal` may give up a jurisdiction by relinquishing an `APPROVED` selection, moving it to `RELINQUISHED`. Relinquishment has a fiscal echo: the `jurisdiction_fee_cents` of every still-`ISSUED` renewal invoice for that registration request is recomputed to reflect the smaller approved-jurisdiction set, and each affected invoice's `total_cents` is recomputed as the sum of its new jurisdiction, pinned base, and pinned surcharge components (§3.7).

### 3.3. Fingerprints and Background Review

Fingerprint capture is recorded per registration request, regardless of the request's current status. A `RegistrationPrincipal` creates a fingerprint submission with the `registration_request_id` and a `submission_channel` of `ELECTRONIC` or `HARD_CARD`; the submission enters `SUBMITTED` status and waits on the FBI result. Processing the result is a `SystemOperator` action with two outcomes. When the payload's `outcome` is `CLEARED`, the submission moves `SUBMITTED → CLEARED`, its `processed_at` is stamped with the server time, and the applicant's `fingerprint_required` recomputes to false. When the `outcome` is `REJECTED`, the submission moves `SUBMITTED → REJECTED`, `processed_at` is likewise stamped, and the illegibility or identity-mismatch cause is recorded verbatim in `rejection_reason` from the payload (null when the payload omits it); the applicant's `fingerprint_required` remains true, and a fresh fingerprint submission may be created to try again. A submission that has left `SUBMITTED` cannot be processed a second time.

Disclosure answers that came back YES route through compliance. A background-disclosure row created with `answer` true enters `review_status` `PENDING_REVIEW`; a row created with `answer` false is stored with `review_status` `CLEARED` immediately at creation. A `ComplianceOfficer` reviews a `PENDING_REVIEW` row by supplying an `outcome` of `CLEARED` or `FLAGGED`, which becomes the row's new `review_status`. The disposition matters downstream in both directions: approval requires every YES answer to be `CLEARED` (§3.5), while a single `FLAGGED` answer is one of the two grounds on which a submitted request can be denied.

### 3.4. Exams: Requirements, Windows, and Credit Expiry

Exam obligations are created automatically the first time a request is submitted, one set per registration category: an `RR` request spawns `SIE`, `S7`, and `S63` requirements; an `IA` request spawns `SIE` and `S66` (the adviser top-off); a `PRINCIPAL` request spawns `SIE`, `S7`, and `S24`. Every obligation starts in `REQUIRED` status. Obligations can also be added ad hoc — for instance after a `registration_category` amendment, and whatever the request's current status — by creating an exam requirement against a `registration_request_id` and `exam_code` drawn from `SIE`, `S7`, `S63`, `S66`, or `S24`; an attempt to add an `exam_code` the request already carries is rejected `ERR_DUPLICATE`.

Sitting an exam happens inside a scheduled window. A `RegistrationPrincipal` schedules a window by naming the `exam_requirement_id` and supplying `window_start` (the inclusive start) and `window_end` (the exclusive end, which must be strictly after the start or the request is rejected `ERR_INVALID_REQUEST`). Scheduling is only possible while the requirement is `REQUIRED`; while another window for the same requirement is `SCHEDULED` or `OPEN` — at most one such window per requirement, enforced with `ERR_DUPLICATE`; and, for any exam other than `SIE`, only once the same registration request's `SIE` obligation is already satisfied or in progress — that is, in `SCHEDULED`, `PASSED`, or `WAIVED` status, since `SIE` is the prerequisite to every top-off exam, with violations rejected `ERR_REFERENTIAL_VIOLATION`. Creating the window moves the requirement `REQUIRED → SCHEDULED`, and the window itself begins in `SCHEDULED`.

Results are recorded by a `SystemOperator` against the window. The window must currently be `SCHEDULED` or `OPEN`. A `result` of `PASS` additionally requires the server clock to sit inside the window — at or after `window_start` and strictly before `window_end`; a pass recorded outside that span is rejected `ERR_TEMPORAL_VIOLATION`. On a pass the window closes to `USED` with `result_recorded` set to `PASS`, the requirement moves to `PASSED`, its `pass_recorded_at` is stamped with the server time, and its `credit_expiry_at` is computed as exactly 120 days after `pass_recorded_at`. On a `result` of `FAIL` or `NO_SHOW` the window likewise closes to `USED` with `result_recorded` set to the recorded outcome, but the requirement cycles back to `REQUIRED`, freeing the principal to schedule a fresh window. A `SCHEDULED` window can instead be cancelled by a `RegistrationPrincipal`, which moves the window to `CANCELLED` and returns the requirement to `REQUIRED`. A `ComplianceOfficer` may also waive a requirement outright — moving it `REQUIRED → WAIVED` — but only while the parent request is still in `DRAFT` or `DEFICIENT`.

Exam credit is perishable. Whenever the server clock is evaluated (§2.5), any requirement in `PASSED` status whose parent registration request is neither `ACTIVE` nor `TERMINATED` and whose `credit_expiry_at` has been reached or passed flips to `EXPIRED` — the boundary is inclusive, so a credit expires exactly at the expiry instant, not one second later. Once a registration has gone `ACTIVE` (or been `TERMINATED`), its exam credits are locked in and never expire. An `EXPIRED` requirement is not a dead end by itself — it exists so that compliance can act: a submitted request carrying an `EXPIRED` exam obligation has become deniable, as the next subsection describes.

### 3.5. Submission, Deficiency Cycles, and the Approval Gate

Submission is the `RegistrationPrincipal`'s hand-off to compliance. Submitting a `DRAFT` request requires that at least one jurisdiction selection exists for it in `SELECTED` status — a first submission without one is rejected `ERR_INVALID_STATE` (409) — and that every YES disclosure answer carries an `explanation_text` of at least 20 characters; the submission stamps `submitted_at` with the server time, records the acting header value as the request's `submitter_user_id` for later segregation-of-duties checks, spawns the category's exam requirements per §3.4, increments the request's `version`, and moves the request `DRAFT → SUBMITTED`. A request returned for deficiency can be resubmitted from `DEFICIENT` by the same submit capability; resubmission re-checks the explanation-length rule (but not the selection-existence rule), stamps a fresh `submitted_at`, and increments `version`, but spawns no new exam requirements — obligations exist from the first submission.

Compliance review has three exits, all reserved for a `ComplianceOfficer` who is not the recorded submitter (self-review is rejected `ERR_SEGREGATION_OF_DUTIES`, §2.9). Returning the request deficient moves `SUBMITTED → DEFICIENT` and increments `deficiency_count` — with a hard stop: when the increment makes the count reach three, the request does not go back to `DEFICIENT` at all but auto-withdraws, landing in `WITHDRAWN` with the full withdrawal cascade applied — every `SELECTED` jurisdiction selection flips to `RELINQUISHED` and every `ISSUED` renewal invoice for the request is voided to `VOID`, exactly as the explicit withdraw action produces. The second return therefore leaves the request `DEFICIENT` with `deficiency_count` at two, and the third return withdraws it. Denial is available only with cause: at least one disclosure answer in `review_status` `FLAGGED`, or at least one exam requirement in `EXPIRED` status; a denial attempted without either ground is rejected `ERR_INVALID_STATE` (409), and this cause check runs ahead of the segregation-of-duties check. Denial moves `SUBMITTED → DENIED` and flips every `SELECTED` jurisdiction selection to `REJECTED`.

Approval is the gated exit. Beyond segregation of duties, the gate itself — evaluated per the validation order in §2.10 and rejected `ERR_REGULATORY_GATE` when it fails — demands all of the following at once: every exam requirement on the request is in `PASSED` or `WAIVED` status; at least one fingerprint submission for the request is `CLEARED`; every disclosure row with `answer` true has `review_status` `CLEARED`; and the applicant's `fingerprint_required` reads false. Approval moves `SUBMITTED → APPROVED`, stamps `approved_at` with the server time, flips every `SELECTED` jurisdiction selection to `APPROVED` — locking each row's `annual_fee_cents` at its current value — and increments the request's `version`.

Approval is not yet activation. The request moves `APPROVED → ACTIVE` as a system transition evaluated when the server clock is set: at the first moment of the calendar day following the approval date — precisely, when the clock's current date is strictly after the date of `approved_at` — the status rolls forward and `version` increments, with no other fields mutated.

The `RegistrationPrincipal` retains one escape hatch before activation: withdrawing a request, available from `DRAFT`, from `DEFICIENT`, or from `SUBMITTED`, moves it to `WITHDRAWN`, flips every `SELECTED` jurisdiction selection to `RELINQUISHED`, voids every renewal invoice still in `ISSUED` status for the request, and increments `version`. `WITHDRAWN`, `DENIED`, and `TERMINATED` are terminal — any further action against a request in one of those states is rejected `ERR_INVALID_STATE`.

### 3.6. Reportable Events and Amendment Filings

Registration does not freeze the U4. When a reportable event occurs, a `RegistrationPrincipal` enters a disclosure event with the `applicant_id` it attaches to, the `event_type` — one of `CRIMINAL_CHARGE`, `REGULATORY_ACTION`, `BANKRUPTCY`, `CIVIL_JUDGMENT`, or `CUSTOMER_COMPLAINT` — and the `event_date`, an ISO date that may not lie in the future relative to the server clock (future-dating is rejected `ERR_TEMPORAL_VIOLATION`). The desk stamps `reported_at` at entry and immediately computes `amendment_due_at`: the amendment deadline, 30 days from `reported_at` under the governing firm's configured deadline basis (§2.6). Because a disclosure event attaches to an applicant rather than to a firm, the governing firm is resolved at event-creation time from the applicant's registrations: it is the firm of the applicant's currently `ACTIVE` registration request — when several are `ACTIVE`, the most recently activated by `approved_at`, ties broken by `created_at` ascending (the same resolution the amendment filing below uses) — and when the applicant has no `ACTIVE` registration at all, the `CALENDAR` basis applies. The event opens in `OPEN` status.

Filing the amendment is the response. A `RegistrationPrincipal` files against an `OPEN` event with the `disclosure_event_id` and a `narrative_text` of at least 20 characters. The applicant must have a registration request in `ACTIVE` status at filing time — without one the filing is rejected `ERR_REFERENTIAL_VIOLATION` — and the server resolves the filing's `registration_request_id` itself: the applicant's currently `ACTIVE` request, choosing the most recently activated by `approved_at` and breaking ties by `created_at` ascending. The filing's `filed_at` is stamped at creation, and its `is_late` is computed by comparing the filing instant against the event's `amendment_due_at`: strictly after the deadline means late. An on-time filing is created with `is_late` false and moves the event `OPEN → AMENDED`; a late filing is created with `is_late` true and moves the event `OPEN → LATE_AMENDED`. Either way the amendment itself enters `FILED` status, from which compliance review takes over — a `ComplianceOfficer` who is not the filer (segregation again) may accept the filing, moving `FILED → ACCEPTED`, a terminal resting state.

The alternative review outcome is the return. A `ComplianceOfficer` other than the filer may return a `FILED` amendment, moving it to `RETURNED`. The return reopens the underlying event — its status reverts to `OPEN` — and its `amendment_due_at` is recomputed from the original `reported_at` under the same deadline basis — the basis that governed the event at its creation is remembered with the event and reused here, unaffected by any later change to the firm's configured basis: the 30-day clock does not restart from the return date, so a firm that sat on a returned amendment files the re-do against whatever remains of the original window. The `RETURNED` amendment row is immutable and remains queryable in that state; putting the event back on file means creating a brand-new amendment filing against the same `disclosure_event_id`, which begins its own `FILED` lifecycle while the old row stays `RETURNED`.

### 3.7. Renewals: Invoices, Fees, and Payment

Continuing registration is billed per calendar year. A `FinanceClerk` issues a renewal invoice by naming the `registration_request_id` of an `ACTIVE` registration and the `cycle_year` it pays for (a calendar year from 2026 through 2100). Issuing against a registration that is not `ACTIVE` is rejected `ERR_FISCAL_VIOLATION`, and at most one invoice may exist per registration request and cycle year — a second issue for the same pair is rejected `ERR_DUPLICATE`, the uniqueness check sitting ahead of the fiscal check in the validation order (§2.10).

The invoice's components are computed at creation and pinned. The `jurisdiction_fee_cents` component is the sum of `annual_fee_cents` over the request's jurisdiction selections in `APPROVED` status — selections in `SELECTED`, `REJECTED`, or `RELINQUISHED` contribute nothing, and a request with no approved selections pays zero here. The `base_fee_cents` component depends on the firm's rank for this registration: count the firm's other registration requests that are `ACTIVE` with an `approved_at` earlier than this request's (ties broken by `created_at` ascending); if there are none this is the firm's first registration of the cycle and the base is 10000 cents, otherwise each additional registration pays 5000 cents. The `late_surcharge_cents` component punishes late issuance: measure the whole days from January 1 of `cycle_year` to the current server date (never less than zero), take the number of full 14-day blocks that fit in that span, and charge 25% of `base_fee_cents` per block, capped at 100% — four or more blocks therefore cost the full base again; the surcharge amount itself is the base times the capped percentage, rounded half-up to whole cents per §2.7. The invoice's `total_cents` is the sum of the three components, each already rounded. An invoice is born in `ISSUED` status.

Because the pinned values can be hard to plan around, the desk also offers a provisional estimate: a `RegistrationPrincipal`, `FinanceClerk`, or `ComplianceOfficer` may ask a registration request for its renewal estimate for a given `cycle_year`, supplied as the `cycle_year` query parameter and required to be an integer from 2026 through 2100 (anything else is rejected `ERR_INVALID_REQUEST`); the estimate is available for a request in any status. The estimate runs the identical formula — same fee schedule, same block arithmetic — but evaluates the firm's rank as of the estimate call (a projected rank) and measures lateness against the current server date; it returns `estimated_total_cents` alongside its `jurisdiction_fee_cents`, `base_fee_cents`, and `late_surcharge_cents` components, and it is never persisted. An estimate may therefore differ from the final invoice if another registration of the same firm activates before the invoice is issued.

Payment is the desk's other OCC-guarded write. A `FinanceClerk` pays an invoice still in `ISSUED` status whose parent registration is still `ACTIVE`; the payload must carry `expected_renewal_invoice_version` equal to the invoice's current `version`, and a mismatch is rejected `ERR_STALE_VERSION` (§2.8). The amount actually collected is not the creation-time `total_cents` but a payment-time recompute: the late surcharge is recalculated using the payment date while the jurisdiction and base components stand as pinned. The stored invoice always shows its creation-time components, and every invoice response — creation, read, list, payment, and void alike — additionally exposes a recomputed `payable_total_cents` reflecting what is due as of the call; the payable amount is never negative, a sanity floor whose violation is `ERR_FISCAL_VIOLATION`. A successful payment moves the invoice `ISSUED → PAID` and increments its `version`. A `FinanceClerk` may instead void an `ISSUED` invoice, moving it to `VOID`, and the desk auto-voids any invoice still `ISSUED` the moment its registration leaves `ACTIVE` — whether by withdrawal (§3.5) or by termination (§3.9).

### 3.8. Dual Registration and Affiliation Control

An applicant registered at one firm may seek a second affiliation. A `RegistrationPrincipal` files an affiliation request naming the `applicant_id`, the `second_firm_id` sought, and the `first_registration_request_id` of the existing registration the dual affiliation builds on. The second firm must differ from the firm on that first registration — a same-firm request is rejected `ERR_REFERENTIAL_VIOLATION` — and the applicant may hold at most one affiliation request in `PENDING` or `APPROVED` status for a given second firm, with repeats rejected `ERR_DUPLICATE`. The request enters `PENDING`.

A `ComplianceOfficer` decides. Approval requires the affiliation to be `PENDING`, the first registration to be `ACTIVE` at decision time (otherwise `ERR_INVALID_STATE`), the second firm genuinely different from the first registration's firm (`ERR_REFERENTIAL_VIOLATION`), and no competing `PENDING` or `APPROVED` affiliation for the same applicant and second firm (`ERR_DUPLICATE`); approval moves `PENDING → APPROVED`. Denial needs only the `PENDING` precondition plus a `denial_reason` string in the payload (a missing or non-string reason is rejected `ERR_INVALID_REQUEST`); it records the supplied `denial_reason` on the row, moving it to `DENIED`. An approved affiliation lives and dies with its first registration: a `ComplianceOfficer` may revoke it, moving `APPROVED → REVOKED`, and termination of the first registration revokes it automatically, with the further cascade described in the next subsection.

### 3.9. Termination Filings, U5 Comments, and Regulatory Inquiries

The Form U5 ends a registration. A `RegistrationPrincipal` files a termination filing against the `registration_request_id` of an `ACTIVE` registration, giving the `termination_reason` — one of `VOLUNTARY`, `PERMITTED_TO_RESIGN`, `DISCHARGED`, or `DECEASED` — and the `termination_date`, an ISO date that may not be in the future relative to the server clock (a future date is rejected `ERR_TEMPORAL_VIOLATION`). Filing stamps `filed_at`, computes `filing_deadline_at` as 30 days from the `termination_date` under the firm's deadline basis (§2.6), and sets `is_late` true when the filing instant falls strictly after that deadline. The filing enters `FILED` status, and the registration itself cascades: the request moves `ACTIVE → TERMINATED` with its `version` incremented; every jurisdiction selection still `APPROVED` flips to `RELINQUISHED`; every renewal invoice still `ISSUED` for the request is voided to `VOID`; and every affiliation request built on this registration as its `first_registration_request_id` and currently `APPROVED` is revoked to `REVOKED`. Each such revocation cascades one level further: the affected applicant loses dual-registration status, and any renewal invoice still `ISSUED` on the second firm's corresponding registration is voided as well.

A filed U5 can be reopened for edits — within limits. A `RegistrationPrincipal` may open the filing for amendment, moving `FILED → AMENDMENT_OPEN`, but only while no regulatory inquiry against this filing sits in `OPEN` or `PENDING_RESPONSE` status — an attempt on a filing in the wrong status, or one blocked by an open inquiry, is rejected `ERR_INVALID_STATE` (409). Opening the amendment window changes only the filing's status; the API exposes no endpoint that edits a termination filing's fields. Closing the amendment window returns the filing `AMENDMENT_OPEN → FILED` and requires that every U5 comment on the filing has `disposition` `CONSISTENT` — a filing not in `AMENDMENT_OPEN`, or one carrying a non-`CONSISTENT` comment, is rejected `ERR_INVALID_STATE` (409).

Comments are how the desk negotiates the U5's wording. Either a `ComplianceOfficer` or a `RegistrationPrincipal` may add a comment to a U5 in any filing status — there is no state precondition on commenting — supplying the `termination_filing_id` and a `comment_text` of at least 10 characters; the server stamps the `author_role` from the acting `X-User-Role` (recorded as `COMPLIANCE_OFFICER` or `REGISTRATION_PRINCIPAL`). Each comment enters `PENDING` disposition and is immediately scored for accuracy against the parent filing's `termination_reason` using a case-insensitive substring scan of the comment text. The contradiction map is fixed: a `VOLUNTARY` termination forbids the substrings "fired", "discharged", and "terminated for cause"; a `PERMITTED_TO_RESIGN` termination forbids "voluntary resignation of"; a `DISCHARGED` termination forbids "resigned voluntarily" and "quit"; a `DECEASED` termination forbids "resigned", "fired", and "discharged". The comment's score is the number of forbidden substrings present in its text: a score of zero leaves the comment `CONSISTENT`, and a score of one or more marks it `INCONSISTENT`. Anything short of all-`CONSISTENT` comments blocks both the close-amendment action above and the final close below.

The terminal act on a U5 belongs to a `ComplianceOfficer` who did not file it (segregation of duties, §2.9): closing moves `FILED → CLOSED` and requires that every comment on the filing is `CONSISTENT` and that every regulatory inquiry attached to the filing is already `CLOSED`; a failed precondition is rejected `ERR_INVALID_STATE` (409), ahead of the segregation-of-duties check.

Regulatory inquiries are the desk's inbound scrutiny. A `Regulator` opens an inquiry by naming the `subject_filing_type` — `REGISTRATION_REQUEST`, `AMENDMENT_FILING`, or `TERMINATION_FILING` — the `subject_filing_id` of the specific filing under examination (which must exist, or the request is `ERR_NOT_FOUND` — resolving the subject requires knowing its type, so on this endpoint the `subject_filing_type` enum and required-field checks run before the subject's existence is resolved, reversing the usual §2.10 order), and an `inquiry_text` of at least 20 characters. At creation the server resolves the `firm_id` from the subject filing's firm, computes `response_due_at` as 15 business days from the creation timestamp under the regulatory deadline basis (always `REGULATORY`, §2.6), sets the status `OPEN`, and recomputes the firm's `open_inquiry_count` — which counts inquiries in `OPEN` or `PENDING_RESPONSE`, so a fresh inquiry raises it. A `SystemOperator` routes an `OPEN` inquiry to the firm, moving it `OPEN → PENDING_RESPONSE`; since both states count toward the firm's open total, routing leaves `open_inquiry_count` unchanged. The firm's answer comes from a `ComplianceOfficer`, who responds with a `response_text` of at least 20 characters while the inquiry is `PENDING_RESPONSE`; a response filed after `response_due_at` is rejected `ERR_TEMPORAL_VIOLATION` — late answers are not accepted. A successful response moves the inquiry to `RESPONDED`, stores the text, and recomputes `open_inquiry_count` down by one, `RESPONDED` being outside the counted set. Finally, a `SystemOperator` closes a `RESPONDED` inquiry, moving it `RESPONDED → CLOSED`; only then does an inquiry stop blocking the U5 close described above.

## 4. Endpoint Definitions

Operations that create a new resource — firms, applicants, registration requests, jurisdiction selections, fingerprint submissions, background disclosures, exam requirements, exam windows, disclosure events, amendment filings, termination filings, U5 comments, affiliation requests, renewal invoices, and regulatory inquiries — return `201 Created`. Operations that act on an existing resource, including all state-transition actions, patches, the clock set, and the provisional estimate read, return `200 OK`. The table below summarizes the HTTP contract only; request payloads, preconditions, and side effects are defined by the narratives of Sections 2 and 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/registration-desk/_clock/set_current_utc` | Set the server logical clock | SystemOperator |
| POST | `/registration-desk/firms` | Create a member firm record | SystemOperator |
| GET | `/registration-desk/firms` | List firms, paginated | SystemOperator, ComplianceOfficer, RegistrationPrincipal, FinanceClerk, Regulator |
| GET | `/registration-desk/firms/{id}` | Read one firm including computed `open_inquiry_count` | SystemOperator, ComplianceOfficer, RegistrationPrincipal, FinanceClerk, Regulator |
| PATCH | `/registration-desk/firms/{id}` | Update firm configuration (`legal_name`, `deadline_basis`, `status`) | SystemOperator |
| POST | `/registration-desk/applicants` | Create an individual applicant record | RegistrationPrincipal |
| GET | `/registration-desk/applicants` | List applicants, paginated | SystemOperator, ComplianceOfficer, RegistrationPrincipal, Regulator |
| GET | `/registration-desk/applicants/{id}` | Read one applicant including computed `fingerprint_required` | SystemOperator, ComplianceOfficer, RegistrationPrincipal, Regulator |
| POST | `/registration-desk/registration-requests` | Create a registration request (U4) in `DRAFT` | RegistrationPrincipal |
| GET | `/registration-desk/registration-requests` | List registration requests with optional filters | SystemOperator, ComplianceOfficer, RegistrationPrincipal, Regulator |
| GET | `/registration-desk/registration-requests/{id}` | Read one registration request | SystemOperator, ComplianceOfficer, RegistrationPrincipal, Regulator |
| PATCH | `/registration-desk/registration-requests/{id}` | Amend `registration_category` while `DRAFT` or `DEFICIENT`; OCC-guarded | RegistrationPrincipal |
| POST | `/registration-desk/registration-requests/{id}/submit` | Submit a `DRAFT` or `DEFICIENT` request | RegistrationPrincipal |
| POST | `/registration-desk/registration-requests/{id}/approve` | Approve a `SUBMITTED` request (regulatory gate applies) | ComplianceOfficer |
| POST | `/registration-desk/registration-requests/{id}/return-deficient` | Return a `SUBMITTED` request to `DEFICIENT`; third return auto-withdraws | ComplianceOfficer |
| POST | `/registration-desk/registration-requests/{id}/deny` | Deny a `SUBMITTED` request (requires a `FLAGGED` disclosure or an `EXPIRED` exam) | ComplianceOfficer |
| POST | `/registration-desk/registration-requests/{id}/withdraw` | Withdraw a request in `DRAFT`, `DEFICIENT`, or `SUBMITTED` | RegistrationPrincipal |
| GET | `/registration-desk/registration-requests/{id}/renewal-estimate` | Provisional renewal fee estimate for a cycle year (not persisted) | RegistrationPrincipal, FinanceClerk, ComplianceOfficer |
| POST | `/registration-desk/jurisdiction-selections` | Add a jurisdiction/SRO selection to a request in `DRAFT` or `DEFICIENT` | RegistrationPrincipal |
| GET | `/registration-desk/jurisdiction-selections` | List jurisdiction selections with optional filters | SystemOperator, ComplianceOfficer, RegistrationPrincipal, Regulator |
| GET | `/registration-desk/jurisdiction-selections/{id}` | Read one jurisdiction selection | SystemOperator, ComplianceOfficer, RegistrationPrincipal, Regulator |
| POST | `/registration-desk/jurisdiction-selections/{id}/relinquish` | Relinquish an `APPROVED` selection on an `ACTIVE` registration | RegistrationPrincipal |
| POST | `/registration-desk/fingerprint-submissions` | Create a fingerprint submission for a request | RegistrationPrincipal |
| GET | `/registration-desk/fingerprint-submissions` | List fingerprint submissions with optional filters | SystemOperator, ComplianceOfficer, RegistrationPrincipal, Regulator |
| GET | `/registration-desk/fingerprint-submissions/{id}` | Read one fingerprint submission | SystemOperator, ComplianceOfficer, RegistrationPrincipal, Regulator |
| POST | `/registration-desk/fingerprint-submissions/{id}/process` | Record the FBI processing outcome (`CLEARED`, or `REJECTED` with `rejection_reason`) | SystemOperator |
| POST | `/registration-desk/background-disclosures` | Record a U4 disclosure question answer on a request | RegistrationPrincipal |
| GET | `/registration-desk/background-disclosures` | List background disclosures with optional filters | SystemOperator, ComplianceOfficer, RegistrationPrincipal, Regulator |
| GET | `/registration-desk/background-disclosures/{id}` | Read one background disclosure | SystemOperator, ComplianceOfficer, RegistrationPrincipal, Regulator |
| POST | `/registration-desk/background-disclosures/{id}/review` | Review a `PENDING_REVIEW` disclosure: outcome `CLEARED` or `FLAGGED` | ComplianceOfficer |
| POST | `/registration-desk/exam-requirements` | Add an exam requirement to a request ad hoc | RegistrationPrincipal |
| GET | `/registration-desk/exam-requirements` | List exam requirements with optional filters | SystemOperator, ComplianceOfficer, RegistrationPrincipal, Regulator |
| GET | `/registration-desk/exam-requirements/{id}` | Read one exam requirement | SystemOperator, ComplianceOfficer, RegistrationPrincipal, Regulator |
| POST | `/registration-desk/exam-requirements/{id}/waive` | Waive a `REQUIRED` exam requirement while the parent request is `DRAFT` or `DEFICIENT` | ComplianceOfficer |
| POST | `/registration-desk/exam-windows` | Schedule an exam sitting window against a requirement | RegistrationPrincipal |
| GET | `/registration-desk/exam-windows` | List exam windows with optional filters | SystemOperator, ComplianceOfficer, RegistrationPrincipal, Regulator |
| GET | `/registration-desk/exam-windows/{id}` | Read one exam window | SystemOperator, ComplianceOfficer, RegistrationPrincipal, Regulator |
| POST | `/registration-desk/exam-windows/{id}/record-result` | Record `PASS` / `FAIL` / `NO_SHOW` for a window | SystemOperator |
| POST | `/registration-desk/exam-windows/{id}/cancel` | Cancel a `SCHEDULED` window; requirement returns to `REQUIRED` | RegistrationPrincipal |
| POST | `/registration-desk/disclosure-events` | Report a disclosure event for an applicant; `amendment_due_at` computed at creation | RegistrationPrincipal |
| GET | `/registration-desk/disclosure-events` | List disclosure events with optional filters | SystemOperator, ComplianceOfficer, RegistrationPrincipal, Regulator |
| GET | `/registration-desk/disclosure-events/{id}` | Read one disclosure event | SystemOperator, ComplianceOfficer, RegistrationPrincipal, Regulator |
| POST | `/registration-desk/amendment-filings` | File a U4 amendment for an `OPEN` disclosure event | RegistrationPrincipal |
| GET | `/registration-desk/amendment-filings` | List amendment filings with optional filters | SystemOperator, ComplianceOfficer, RegistrationPrincipal, Regulator |
| GET | `/registration-desk/amendment-filings/{id}` | Read one amendment filing | SystemOperator, ComplianceOfficer, RegistrationPrincipal, Regulator |
| POST | `/registration-desk/amendment-filings/{id}/accept` | Accept a `FILED` amendment | ComplianceOfficer |
| POST | `/registration-desk/amendment-filings/{id}/return` | Return a `FILED` amendment; parent event reverts to `OPEN` with the original deadline | ComplianceOfficer |
| POST | `/registration-desk/termination-filings` | File a U5 terminating an `ACTIVE` registration | RegistrationPrincipal |
| GET | `/registration-desk/termination-filings` | List termination filings with optional filters | SystemOperator, ComplianceOfficer, RegistrationPrincipal, Regulator |
| GET | `/registration-desk/termination-filings/{id}` | Read one termination filing | SystemOperator, ComplianceOfficer, RegistrationPrincipal, Regulator |
| POST | `/registration-desk/termination-filings/{id}/open-amendment` | Open a `FILED` U5 for amendment (blocked while an inquiry on it is open) | RegistrationPrincipal |
| POST | `/registration-desk/termination-filings/{id}/close-amendment` | Close an `AMENDMENT_OPEN` U5 (requires all comments `CONSISTENT`) | RegistrationPrincipal |
| POST | `/registration-desk/termination-filings/{id}/close` | Close a `FILED` U5 (requires all comments `CONSISTENT` and all inquiries `CLOSED`) | ComplianceOfficer |
| POST | `/registration-desk/u5-comments` | Add a comment to a U5; disposition computed on creation | ComplianceOfficer, RegistrationPrincipal |
| GET | `/registration-desk/u5-comments` | List U5 comments with optional filters | SystemOperator, ComplianceOfficer, RegistrationPrincipal, Regulator |
| GET | `/registration-desk/u5-comments/{id}` | Read one U5 comment | SystemOperator, ComplianceOfficer, RegistrationPrincipal, Regulator |
| POST | `/registration-desk/affiliation-requests` | Request dual registration with a second firm | RegistrationPrincipal |
| GET | `/registration-desk/affiliation-requests` | List affiliation requests with optional filters | SystemOperator, ComplianceOfficer, RegistrationPrincipal, Regulator |
| GET | `/registration-desk/affiliation-requests/{id}` | Read one affiliation request | SystemOperator, ComplianceOfficer, RegistrationPrincipal, Regulator |
| POST | `/registration-desk/affiliation-requests/{id}/approve` | Approve a `PENDING` affiliation | ComplianceOfficer |
| POST | `/registration-desk/affiliation-requests/{id}/deny` | Deny a `PENDING` affiliation with a reason | ComplianceOfficer |
| POST | `/registration-desk/affiliation-requests/{id}/revoke` | Revoke an `APPROVED` affiliation | ComplianceOfficer |
| POST | `/registration-desk/renewal-invoices` | Issue a renewal invoice for an `ACTIVE` registration and cycle year | FinanceClerk |
| GET | `/registration-desk/renewal-invoices` | List renewal invoices with optional filters | SystemOperator, ComplianceOfficer, RegistrationPrincipal, FinanceClerk, Regulator |
| GET | `/registration-desk/renewal-invoices/{id}` | Read one renewal invoice including recomputed `payable_total_cents` | SystemOperator, ComplianceOfficer, RegistrationPrincipal, FinanceClerk, Regulator |
| POST | `/registration-desk/renewal-invoices/{id}/pay` | Pay an `ISSUED` invoice; OCC-guarded; collected amount is the payment-time recompute | FinanceClerk |
| POST | `/registration-desk/renewal-invoices/{id}/void` | Void an `ISSUED` invoice | FinanceClerk |
| POST | `/registration-desk/regulatory-inquiries` | Open a regulatory inquiry against a filing | Regulator |
| GET | `/registration-desk/regulatory-inquiries` | List regulatory inquiries with optional filters | SystemOperator, ComplianceOfficer, RegistrationPrincipal, Regulator |
| GET | `/registration-desk/regulatory-inquiries/{id}` | Read one regulatory inquiry | SystemOperator, ComplianceOfficer, RegistrationPrincipal, Regulator |
| POST | `/registration-desk/regulatory-inquiries/{id}/route` | Route an `OPEN` inquiry to the firm | SystemOperator |
| POST | `/registration-desk/regulatory-inquiries/{id}/respond` | Respond to a `PENDING_RESPONSE` inquiry before `response_due_at` | ComplianceOfficer |
| POST | `/registration-desk/regulatory-inquiries/{id}/close` | Close a `RESPONDED` inquiry | SystemOperator |

## 5. Error Code Catalogue

The desk's machine-readable error identifiers and their HTTP statuses are listed below. The conditions that trigger each error are defined in the narratives of Sections 2 and 3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_DUPLICATE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_REGULATORY_GATE` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_TEMPORAL_VIOLATION` | 422 Unprocessable Entity |
| `ERR_REFERENTIAL_VIOLATION` | 422 Unprocessable Entity |
| `ERR_FISCAL_VIOLATION` | 422 Unprocessable Entity |
