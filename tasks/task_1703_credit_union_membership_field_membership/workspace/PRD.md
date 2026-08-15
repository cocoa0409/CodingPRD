# Credit Union Membership & Field of Membership API — Product Requirements Document

## 1. Introduction

A federally chartered credit union may serve only persons who fall within an approved field of membership, and examiners expect documentary proof of that eligibility for every member on the books. Eligibility is not a one-time decision, either: employers leave the charter, associational ties lapse, and members who no longer qualify must be identified, granted a statutory cure window, and — failing cure — have their accounts wound down in an orderly, auditable way. This API is the system of record for that entire regulatory lifecycle: the charter that defines the field of membership, the amendments that expand or retire it, the applications that admit members against it, the share accounts and dividends that constitute membership itself, the annual meeting that governs the institution, and the eligibility reviews that enforce it over time.

The operating model is one of strict segregation of duties. The officer who files a membership application may never decide it; the compliance officer who flags an eligibility concern may never adjudicate it; the director who declares a dividend may never run its payment; and the compliance officer who files a charter amendment hands the decision to an external regulator. All domain resources are mounted under `/credit-union`. Every mutation, including cascades and recomputations, is atomic and visible in the same response and in every subsequent read. All regulatory timing — an amendment taking effect, a grace period expiring, a dividend becoming payable — is driven by a single logical clock rather than wall time, so the full compliance calendar is reproducible and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across every resource and every workflow; §3 then develops each business process in narrative form.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their capacity. A request missing either header, or carrying an empty value for either, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not permitted on the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`. The system recognizes exactly seven roles: `Member`, `MembershipOfficer`, `ComplianceOfficer`, `Regulator`, `BoardDirector`, `OperationsOfficer`, and `SystemAdmin`.

When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting Member; ownership checks on any resource that references a Member compare the resource's member-reference field to `X-User-ID`. Wherever the `Member` role is permitted — reading a member record, that member's share accounts, their transactions, their dividend payments, their ballots, and casting a ballot — the `X-User-ID` must equal the `id` of the member addressed by the path (for share-account paths, the member who owns the account). A member touching another member's resources is rejected with `ERR_NOT_RESOURCE_OWNER`; the ballot a member casts is always attributed to the caller.

When `X-User-Role` is `MembershipOfficer`, `ComplianceOfficer`, `Regulator`, `BoardDirector`, `OperationsOfficer`, or `SystemAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it — for example as `filed_by_user_id` on a membership application, `submitted_by_user_id` on a charter amendment application, `flagged_by_user_id` on an eligibility review, or `declared_by_user_id` on a dividend declaration — but never compares it to any entity's `id`. These operator identifiers nevertheless anchor the segregation-of-duties comparisons described in §2.10.

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

List endpoints paginate via the query parameters `limit` and `offset`. The `limit` parameter caps the number of items returned: it defaults to 10, may not be less than 1, and may not exceed 100. The `offset` parameter states how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp records creation as an ISO 8601 UTC value with three fractional digits. The `updated_at` timestamp is refreshed on any change to the resource. The `version` is a system-managed integer that increments with every modification to the resource — including cascade-driven state changes and rewrites of derived fields — and serves as the basis for optimistic concurrency control. Two resources are deliberately leaner: a ShareTransaction and a Ballot are immutable ledger records that carry only `id` and `created_at`; both `updated_at` and `version` are absent from them.

### 2.5. The Logical Clock and Scheduled Lifecycle Sweeps

One logical clock governs every date comparison in the system — the "current date" that approval stamps, posting windows, voting windows, maturity checks, and tenure arithmetic all read from it. At startup the clock reads exactly `2026-08-01T00:00:00Z`; it never follows wall-clock time. A SystemAdmin-only, test-driving capability sets the clock to a supplied `to_iso8601` instant. Each clock set runs the epoch sweep: every APPROVED charter amendment whose `effective_date` has been reached becomes EFFECTIVE with the cascades of §3.2, and every GRACE_PERIOD member whose `grace_end_date` has been reached is closed with the forced-closure cascade of §3.9.

### 2.6. Validation Order and Error Precedence

Every request passes through an ordered ladder of validation tiers. The first tier that fails determines the error returned; later tiers are never consulted for a request that has already been rejected. The tiers, in order, are:

1. **Authentication context.** `X-User-ID` and `X-User-Role` must be present and non-empty on every endpoint, otherwise `ERR_UNAUTHENTICATED` (401).
2. **Role authorization.** The supplied role must be permitted on the endpoint per §2.1 and §4, otherwise `ERR_FORBIDDEN_ROLE` (403).
3. **Member ownership.** Where the `Member` role is permitted, the caller may only touch their own records, otherwise `ERR_NOT_RESOURCE_OWNER` (403).
4. **Syntactic validity.** Required fields must be present, types must be correct, enum values must be in range, and basis-dependent field combinations must hold — a SEGMENT_MATCH application requires `segment_id`; a FAMILY or HOUSEHOLD application requires `sponsor_member_id` and `relationship_to_sponsor`; an ADD_SEGMENT amendment requires the `proposed_segment_type`, `proposed_segment_descriptor`, and `proposed_segment_required_documents` fields; a RETIRE_SEGMENT amendment requires a non-empty `retire_segment_ids`. Any failure is `ERR_VALIDATION_FAILED` (400). This tier applies to all endpoints.
5. **Existence.** Path identifiers and body foreign-key references must exist, validated left to right, otherwise `ERR_NOT_FOUND` (404). This tier applies to all endpoints.
6. **Stale-version guards.** The two optimistic-concurrency checks of §2.7 — `expected_charter_version` against the charter's current `version` on amendment filing, and `expected_member_version` against the member's current `version` on a profile update — are evaluated after existence and before any state-machine or business check, otherwise `ERR_STALE_CHARTER_VERSION` or `ERR_STALE_MEMBER_VERSION` (412).
7. **State-machine preconditions.** The member must be ACTIVE for account opening, enrollment, ballot casting, or manual review creation (`ERR_MEMBER_NOT_ACTIVE`); the account must be OPEN for transactions and close (`ERR_ACCOUNT_NOT_OPEN`); the application, amendment, declaration, meeting, or review must be in the required from-state (`ERR_APPLICATION_INVALID_STATE`, `ERR_AMENDMENT_INVALID_STATE`, `ERR_DECLARATION_INVALID_STATE`, `ERR_MEETING_INVALID_STATE`, `ERR_REVIEW_INVALID_STATE`); and the ballot-specific voter eligibility rule (`ERR_MEMBER_NOT_ELIGIBLE_TO_VOTE`, 403 — the sole non-409 in this tier). Within this tier, the target resource named left-most in the path is checked first — on a ballot cast, the meeting's state is validated before the voter's eligibility.
8. **Regulatory evidence.** Documentation completeness, sponsor eligibility, and segregation of duties — `ERR_DOCUMENTATION_INCOMPLETE` and `ERR_SPONSOR_NOT_ELIGIBLE` (422), `ERR_SEGREGATION_OF_DUTIES` (403). This tier applies to membership-application approve and deny, and to eligibility-review cure and confirm-ineligible.
9. **Referenced-entity state and configuration.** Segment ACTIVE, funding account owned and OPEN, proposed segment type compatible with the charter's bond — `ERR_SEGMENT_NOT_ACTIVE` (409), `ERR_PRODUCT_FUNDING_ACCOUNT_INVALID` and `ERR_BOND_TYPE_MISMATCH` (both 422). This tier applies to membership-application create and approve, product-enrollment create, and amendment create.
10. **Uniqueness and bands.** Charter singleton, one PRIMARY account per member, one ACTIVE enrollment per member and product, one ballot per member per reconvene chain, the dividend rate band, and the product's tier requirement — `ERR_CHARTER_ALREADY_EXISTS`, `ERR_PRIMARY_ACCOUNT_EXISTS`, `ERR_ALREADY_ENROLLED`, `ERR_BALLOT_ALREADY_CAST_IN_CHAIN` (409), `ERR_DIVIDEND_RATE_OUT_OF_BAND` (422), `ERR_TIER_REQUIREMENT_NOT_MET` (403). This tier applies to charter create, share-account create, enrollment create, ballot create, and dividend-declaration create.
11. **Temporal rules.** Dividend period overlap, the meeting thirty-day gap, the voting window, the amendment effective date, the payable-date ordering, and the transaction posting window — `ERR_DIVIDEND_PERIOD_OVERLAP`, `ERR_MEETING_TOO_CLOSE`, `ERR_VOTING_WINDOW_CLOSED`, `ERR_DIVIDEND_NOT_YET_PAYABLE` (409), and `ERR_EFFECTIVE_DATE_NOT_FUTURE`, `ERR_DATE_ORDER_INVALID`, `ERR_INVALID_TRANSACTION_DATE` (422). This tier applies to declaration create and pay, meeting create, ballot create, amendment create and approve, and transaction create.
12. **Funds and par value.** Opening-deposit and withdrawal floors — `ERR_BELOW_PAR_VALUE`, `ERR_PAR_VALUE_BREACH`, `ERR_INSUFFICIENT_FUNDS` (all 422). This tier applies to share-account create and transaction create.

### 2.7. Optimistic Concurrency Control

Two write surfaces are guarded by optimistic concurrency control, and only these two. A request filing a charter amendment (`POST /credit-union/charter-amendment-applications`) must carry `expected_charter_version`, the charter `version` the filer last observed. If the charter's version has advanced since then — every successful amendment submission and every amendment becoming EFFECTIVE advances it — the filing is rejected with `ERR_STALE_CHARTER_VERSION` (HTTP 412), forcing the filer to refresh their view before restating the field of membership. A request updating a member profile (`PATCH /credit-union/members/{id}`) must carry `expected_member_version`, the member `version` the caller last read; tier reviews and eligibility cascades also advance the member's version, and a mismatch is rejected with `ERR_STALE_MEMBER_VERSION` (HTTP 412) so a profile update never overwrites a member record the caller has not observed. Endpoints not named here accept no version field at all.

### 2.8. Money, Dates, and Derived Balances

All monetary quantities are integer cents — never floating-point, never fractional. Where a computation produces a fractional cent, the per-account amount is rounded half-up to integer cents exactly once, and that per-account rounding always precedes any summation; summing raw values first and rounding once is forbidden because it yields a different total. Tier threshold comparisons are integer-cent comparisons with no rounding. Calendar dates are `YYYY-MM-DD` strings compared against the logical clock's current date. Finally, share-account balances are derived, never accepted as input: every account balance and every dividend computation is produced by the chronological ledger replay defined in §3.5, so backdated history is always honored in full.

### 2.9. Nested Resource Retrieval

Requests that address nested resources — a segment under a charter, an account under a member, a ballot under a meeting — validate each path identifier in strict left-to-right order and are rejected with `ERR_NOT_FOUND` (404) at the first identifier that does not correspond to an existing resource. Body foreign-key references are likewise existence-checked at the same tier. No business or state rule is evaluated against a resource that has not first been found to exist.

### 2.10. Segregation of Duties

Regulatory decisions are structurally separated from their initiation. The officer who files a membership application (recorded as `filed_by_user_id`) may never be the one who approves or denies it; the officer who flags an eligibility review (`flagged_by_user_id`) may never be the one who cures or confirms it. A deciding user whose `X-User-ID` equals the filer's or flagger's is rejected with `ERR_SEGREGATION_OF_DUTIES` (403). The same principle is enforced by role boundaries: a `ComplianceOfficer` files charter amendments while a `Regulator` approves or denies them, and a `BoardDirector` declares and voids dividends while an `OperationsOfficer` runs the payment — the declaring director never moves the money.

### 2.11. Member Posture Gating

A member's eligibility posture gates what the institution will do for them. Account opening, product enrollment, ballot casting, and the creation of a manual eligibility review all require the member to be ACTIVE (for manual review creation, GRACE_PERIOD is also accepted, enabling late cure); a member not in an accepted posture is rejected with `ERR_MEMBER_NOT_ACTIVE`. Ballot casting applies its own voter-eligibility companion rule with `ERR_MEMBER_NOT_ELIGIBLE_TO_VOTE`, detailed in §3.8. Posture itself is driven by the review lifecycle of §3.9 and by the segment-retirement cascade of §3.2, so a single regulatory event can shift many members' postures at once.

## 3. Business Logic & Workflows

### 3.1. The Charter and Its Field of Membership

A `BoardDirector` establishes the credit union by creating its charter. The creation payload carries the `bond_type` — one of `SINGLE_OCCUPATIONAL`, `COMMUNITY`, `ASSOCIATIONAL`, or `MULTIPLE_COMMON_BOND` — together with `par_value_cents`, a positive integer number of cents fixing the par value of one membership share, and a `segments` array describing the initial field of membership. The charter is a singleton with status always ACTIVE: exactly one may exist, and a second creation attempt is rejected with `ERR_CHARTER_ALREADY_EXISTS`. The charter also carries a free-text `note`, empty at creation.

Each element of the `segments` array becomes an EligibilitySegment defined by its `segment_type` (`OCCUPATIONAL`, `COMMUNITY`, or `ASSOCIATIONAL`), a `descriptor` holding the employer name, community definition, or association name, and `required_documents`, a subset of the five recognized evidence codes `GOVERNMENT_ID`, `EMPLOYER_LETTER`, `ADDRESS_PROOF`, `ASSOCIATION_CARD`, and `RELATIONSHIP_PROOF`. One segment is created per array element, in array order, each beginning ACTIVE with `retired_at` null and a `charter_id` tying it to its charter.

The charter's `version` is the baseline against which all amendment activity is measured: it increments by one on every successful amendment submission and by one again whenever an amendment becomes EFFECTIVE. Reading the charter therefore exposes everything a filer needs for baselining, and the charter's segment list and amendment-application list — each filterable by `status` and paginated with `limit` and `offset` — give officers and the regulator a complete view of the field of membership's current shape and pending changes.

### 3.2. Amending the Charter: Expansion, Retirement, and the Regulatory Decision

When the board seeks to grow or reshape the field of membership, a `ComplianceOfficer` files a charter amendment application carrying `charter_id`, the `amendment_type` (`ADD_SEGMENT` or `RETIRE_SEGMENT`), an `effective_date`, and the optimistic-concurrency field `expected_charter_version`. The payload's shape depends on the type: an ADD_SEGMENT filing must name the `proposed_segment_type`, `proposed_segment_descriptor`, and `proposed_segment_required_documents`, while a RETIRE_SEGMENT filing must list a non-empty `retire_segment_ids` array; filings that omit the combination their type demands are rejected as malformed with `ERR_VALIDATION_FAILED`. The `effective_date` must be strictly later than the current clock date at submission, otherwise `ERR_EFFECTIVE_DATE_NOT_FUTURE`. A filing whose `expected_charter_version` no longer matches the charter is rejected with `ERR_STALE_CHARTER_VERSION` per §2.7 — and because every accepted submission immediately increments the charter's version, two filings built on the same baseline can never both succeed. On acceptance the application begins SUBMITTED, the filer is recorded as `submitted_by_user_id`, and the accepted expected version is preserved as `baseline_charter_version`.

Bond-type compatibility constrains expansion. A single-bond charter accepts only its own segment type — `SINGLE_OCCUPATIONAL` admits only `OCCUPATIONAL` segments, `COMMUNITY` only `COMMUNITY`, `ASSOCIATIONAL` only `ASSOCIATIONAL` — while a `MULTIPLE_COMMON_BOND` charter accepts any of the three. A filing that proposes an incompatible segment type is rejected with `ERR_BOND_TYPE_MISMATCH`.

The decision belongs to the `Regulator` alone. Approval requires the application to still be SUBMITTED — anything else yields `ERR_AMENDMENT_INVALID_STATE` — and requires the `effective_date` to remain strictly later than the current clock date at the moment of approval, otherwise `ERR_EFFECTIVE_DATE_NOT_FUTURE`; a successful approval records the deciding regulator as `decided_by_user_id` and moves the application to APPROVED. Denial likewise requires SUBMITTED, records the supplied `denial_reason`, and moves the application to DENIED. DENIED is terminal; nothing further can happen to a denied filing.

Maturation is the clock's work. When the epoch sweep finds an APPROVED amendment whose `effective_date` has been reached, the amendment becomes EFFECTIVE; the sweep applies all maturing amendments in order of `effective_date` ascending, ties broken by `created_at` ascending, and each one increments the charter's `version` by one. An EFFECTIVE ADD_SEGMENT amendment creates a new ACTIVE EligibilitySegment from the proposed fields and records its id as the application's `applied_segment_id`. An EFFECTIVE RETIRE_SEGMENT amendment moves every listed segment to RETIRED with `retired_at` set to the current date, and each retirement cascades: for every Member whose `segment_id` is the retired segment, whose `eligibility_basis` is SEGMENT_MATCH, and whose status is ACTIVE, the system opens an EligibilityReview in OPEN status with reason SEGMENT_RETIRED and `flagged_by_user_id` recorded as 'system', and moves that member to INELIGIBLE_UNDER_REVIEW. EFFECTIVE is terminal, closing the application's lifecycle.

### 3.3. Membership Applications: Filing, Documentation, and Adjudication

A `MembershipOfficer` opens the membership relationship by filing an application carrying the `applicant_full_name`, `date_of_birth`, the eligibility `basis` — `SEGMENT_MATCH`, `FAMILY`, or `HOUSEHOLD` — and the `documents_provided` already in hand. The basis dictates the rest of the payload: a SEGMENT_MATCH application must reference a `segment_id`, while FAMILY and HOUSEHOLD applications must name a `sponsor_member_id` and a `relationship_to_sponsor` — one of `SPOUSE`, `CHILD`, `PARENT`, `SIBLING`, `GRANDPARENT`, or `GRANDCHILD` for FAMILY, or `HOUSEHOLD_MEMBER` for HOUSEHOLD. Combinations that do not match the declared basis are rejected with `ERR_VALIDATION_FAILED`. A new application begins UNDER_REVIEW, with the filing officer recorded as `filed_by_user_id`.

Documentation requirements are computed, not declared. For SEGMENT_MATCH the application's `required_documents` are inherited from the referenced segment's `required_documents`; FAMILY requires `GOVERNMENT_ID` and `RELATIONSHIP_PROOF`; HOUSEHOLD requires `GOVERNMENT_ID` and `ADDRESS_PROOF`. The boolean `docs_complete` is true exactly when every required code appears among the `documents_provided`. Referenced parties must be eligible at filing: an application citing a segment that is not ACTIVE is rejected with `ERR_SEGMENT_NOT_ACTIVE`, and a FAMILY or HOUSEHOLD application whose sponsor member is not ACTIVE is rejected with `ERR_SPONSOR_NOT_ELIGIBLE`. Both checks are re-evaluated at approval time.

Evidence gathering is a loop. While an application is UNDER_REVIEW, an officer may request additional documents, which moves it to DOCS_REQUESTED and replaces `requested_document_codes` with the codes named in the request. When the applicant's supplemental evidence arrives, submitting documents returns the application to UNDER_REVIEW: the newly supplied `documents_provided` are unioned with those already on file — earlier evidence is never lost — and `docs_complete` is recomputed. Each leg of the loop requires its matching from-state; requesting documents from an application that is not UNDER_REVIEW, or submitting against one that is not DOCS_REQUESTED, fails with `ERR_APPLICATION_INVALID_STATE`. The loop may cycle as many times as the evidence demands.

Approval is the gate to membership, and it enforces four conditions: `docs_complete` must be true, otherwise `ERR_DOCUMENTATION_INCOMPLETE`; a SEGMENT_MATCH application's segment must be ACTIVE at approval time, otherwise `ERR_SEGMENT_NOT_ACTIVE`; a FAMILY or HOUSEHOLD application's sponsor must be ACTIVE at approval time, otherwise `ERR_SPONSOR_NOT_ELIGIBLE`; and the deciding officer's `X-User-ID` must differ from the application's `filed_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`. An approved application becomes APPROVED — terminal — and in the same atomic step the system creates the Member: status ACTIVE, tier STANDARD, `membership_effective_date` set to the current clock date, with `application_id`, `full_name`, `date_of_birth`, `eligibility_basis`, `segment_id`, `sponsor_member_id`, and `relationship_to_sponsor` all carried over from the application, whose `resulting_member_id` is set to the new member's id.

Denial is available from both UNDER_REVIEW and DOCS_REQUESTED, and in either state it demands the same segregation of duties — a decider who filed the application is rejected with `ERR_SEGREGATION_OF_DUTIES` — records the supplied `denial_reason`, and lands the application in DENIED, its other terminal state. For casework visibility, the application list can be filtered by `status`, `segment_id`, `sponsor_member_id`, and `resulting_member_id`, in addition to the standard pagination parameters.

### 3.4. The Member Record: Contact Maintenance, Tenure, and Service Tiers

A member record aggregates the identity and provenance copied at approval, a `status` that begins ACTIVE, and the institution's running view of the relationship. Two derived quantities anchor product eligibility. The `tenure_months` of a member is the number of full calendar months between `membership_effective_date` and the current date: twelve times the calendar-year difference plus the calendar-month difference, reduced by one when the current day-of-month precedes the effective date's day-of-month. The `qualifying_balance_cents` is the point-in-time sum of `balance_cents` across the member's OPEN share accounts. The member list can be filtered by `status`, `tier`, `segment_id`, `sponsor_member_id`, or `application_id`.

Contact maintenance is a `MembershipOfficer` duty. Updating a member's contact fields — `mailing_address`, `email`, and `phone` — requires `expected_member_version` matching the member's current `version`; a stale read is rejected with `ERR_STALE_MEMBER_VERSION` per §2.7, and a successful update increments the version. Because tier reviews and eligibility cascades also advance the version, a profile edit must always be based on a fresh read of the member.

The materialized `tier` — STANDARD at admission — changes only through a tier review performed by an `OperationsOfficer`. A tier review evaluates the member on the trailing-ninety-day-average basis: for each day in the ninety-day window comprising the evaluation date and the eighty-nine days preceding it, the member's daily aggregate end-of-day balance is the sum across the share accounts open on that day, and the balance basis is the average of those daily aggregates. PREMIER requires tenure of at least 36 full months and a balance basis of at least 2,500,000 cents; failing that, SELECT requires at least 12 full months and at least 500,000 cents; otherwise the member is STANDARD. Both thresholds are inclusive — a member sitting exactly on a boundary qualifies for the higher tier. The review stamps `last_tier_review_at` and increments the member's `version`. Because the enrollment-time evaluation of §3.6 uses the instantaneous balance rather than the trailing average, the same member on the same day can qualify for a product at enrollment yet evaluate to a lower tier at review, and the materialized tier never changes except through this review.

### 3.5. Share Accounts and the Transaction Ledger

Membership becomes real when a `MembershipOfficer` opens a share account for an ACTIVE member — any other posture fails with `ERR_MEMBER_NOT_ACTIVE` — supplying the `member_id`, an `account_type` of `PRIMARY` or `SUPPLEMENTAL`, and an `initial_deposit_cents`. Every member holds exactly one PRIMARY account; a second attempt is rejected with `ERR_PRIMARY_ACCOUNT_EXISTS`. The PRIMARY account is where par value bites: its opening deposit must be at least the charter's `par_value_cents`, with a deposit of exactly par qualifying, and anything less rejected with `ERR_BELOW_PAR_VALUE`. Opening writes the account's first ledger entry — a ShareTransaction of kind DEPOSIT with `origin` SYSTEM, posted on the current clock date — sets `opened_date` to the current date, and begins the account OPEN. The account's `balance_cents` is never accepted as input; it is always derived from the ledger.

Day-to-day movement is posted by an `OperationsOfficer` as a transaction carrying a `kind` of DEPOSIT or WITHDRAWAL — the posting endpoint accepts only these two kinds, though the ledger also records the system-written DIVIDEND_CREDIT and CLOSURE_DISBURSEMENT kinds — a positive integer `amount_cents`, and a `posted_date`. Backdating is permitted within bounds: the `posted_date` must be on or after the account's `opened_date` and on or before the current clock date, otherwise `ERR_INVALID_TRANSACTION_DATE`. The account must be OPEN, otherwise `ERR_ACCOUNT_NOT_OPEN`. Every endpoint-posted row carries `origin` MANUAL, and every posting increments the account's `version`.

Balances are produced by chronological replay. All of an account's ShareTransaction rows are ordered by `posted_date` ascending with ties broken by `created_at` ascending; replaying in that order, DEPOSIT and DIVIDEND_CREDIT rows add their `amount_cents` while WITHDRAWAL and CLOSURE_DISBURSEMENT rows subtract theirs; each row's `running_balance_cents` captures the balance immediately after it, and the account's `balance_cents` equals the running balance of the final row. A backdated insert re-runs the full replay and rewrites the running balances of every later row, so history is always internally consistent. The transaction list returns rows in exactly this replay order, and each row's `share_account_id` ties it to its account.

Withdrawal floors differ by account type. A WITHDRAWAL on a PRIMARY account must leave the balance at no less than the charter's `par_value_cents` — a withdrawal that would take the account below par is rejected with `ERR_PAR_VALUE_BREACH` — while a SUPPLEMENTAL account merely bottoms out at zero, with a withdrawal exceeding the balance rejected with `ERR_INSUFFICIENT_FUNDS`.

Closure comes in two forms. A `MembershipOfficer` may manually close an OPEN account — closing one in any other state fails with `ERR_ACCOUNT_NOT_OPEN` — but a manual close of the PRIMARY account is permitted only while the owning member is not ACTIVE; attempting it for an ACTIVE member fails with `ERR_PRIMARY_ACCOUNT_REQUIRED`. The system-driven ineligibility cascade of §3.9 bypasses that guard. Either way, closure writes a SYSTEM transaction of kind CLOSURE_DISBURSEMENT for the full balance, posted on the current date, driving `balance_cents` to zero; `closed_date` is set and `closure_reason` records MANUAL or FORCED_INELIGIBILITY. Every ACTIVE ProductEnrollment funded by the closing account is closed in the same step with closure reason FORCED_ACCOUNT_CLOSURE — the only transition an enrollment ever makes.

### 3.6. Product Enrollment and Tier-Gated Offerings

Three products sit behind the service tiers, and a `MembershipOfficer` enrolls an ACTIVE member — any other posture fails with `ERR_MEMBER_NOT_ACTIVE` — by supplying the `member_id`, the `product_code` (`MONEY_MARKET`, `SHARE_CERTIFICATE`, or `PREMIER_LOAN`), and a `funding_share_account_id`. The funding account must belong to that member and be OPEN, otherwise `ERR_PRODUCT_FUNDING_ACCOUNT_INVALID`. A member may hold only one ACTIVE enrollment per product code; a duplicate is rejected with `ERR_ALREADY_ENROLLED`.

Each product names its `required_tier`: MONEY_MARKET and SHARE_CERTIFICATE require SELECT, and PREMIER_LOAN requires PREMIER. Eligibility is evaluated at enrollment on the current-point-in-time basis — the same tenure thresholds and inclusive boundaries as §3.4 (PREMIER at no less than 36 full months and 2,500,000 cents, SELECT at no less than 12 full months and 500,000 cents), but applied to the instantaneous sum of `balance_cents` across the member's OPEN accounts rather than to the materialized tier or any trailing average, so a member with a recent large deposit qualifies immediately. Falling short of the product's tier is rejected with `ERR_TIER_REQUIREMENT_NOT_MET`. The computed tier is recorded on the enrollment as `tier_at_enrollment` alongside the `required_tier`. An enrollment begins ACTIVE and closes only when its funding account closes, ending CLOSED with closure reason FORCED_ACCOUNT_CLOSURE. The enrollment list can be filtered by `member_id`, `funding_share_account_id`, `product_code`, and `status`.

### 3.7. Dividends: Declaration, Accrual, Void, and Payment

A `BoardDirector` declares a dividend for a closed period by supplying `period_start` and `period_end` — a closed interval in which both boundary days count — a `rate_bps` expressing the nominal annual rate in basis points, a `method` of `AVERAGE_DAILY_BALANCE` or `MINIMUM_DAILY_BALANCE`, and a `payable_date`. The rate must sit within the board-authorized band of 10 to 1500 basis points inclusive, otherwise `ERR_DIVIDEND_RATE_OUT_OF_BAND`. The `payable_date` must fall strictly after `period_end`, otherwise `ERR_DATE_ORDER_INVALID`. The new period must not overlap any existing declaration in DECLARED or PAID status — intervals are closed, so sharing even a single boundary day constitutes overlap — otherwise `ERR_DIVIDEND_PERIOD_OVERLAP`; VOIDED declarations no longer block. A declaration begins DECLARED with the director recorded as `declared_by_user_id`, and the chosen `method` is pinned at declaration and reused unchanged at payment time.

Declaration triggers the provisional accrual. The eligible set is every share account that is OPEN at computation time with an `opened_date` on or before `period_end`; CLOSED accounts are excluded entirely. Eligible accounts are processed — and their DividendPayment rows created — in order of `opened_date` ascending, ties broken by `created_at` ascending. For each account the accrual window runs from the later of `period_start` and the account's `opened_date` through `period_end`, both boundary days included, and the window's day count is the number of calendar days it spans. The end-of-day balance for any day is the balance produced by replaying every transaction whose `posted_date` is on or before that day, in replay order. The effective annual rate is the declaration's `rate_bps` plus a tier bonus on the owner's tier — zero basis points for STANDARD, 25 for SELECT, 50 for PREMIER — and at declaration the bonus uses the member's tier as of the declaration date. Under `AVERAGE_DAILY_BALANCE` the raw dividend is the sum of the window's end-of-day balances, multiplied by the effective rate (basis points divided by ten thousand) and divided by 365, the fixed day-count year. Under `MINIMUM_DAILY_BALANCE` the raw dividend is the window's lowest end-of-day balance, multiplied by the effective rate and by the window's day count, divided by 365 — for identical inputs it yields a strictly smaller amount whenever the balance ever dips below its window maximum. A minimum-balance gate guards both methods: when the sum of the window's end-of-day balances divided by the day count falls below 500 cents, the account earns nothing and no payment row is created for it at accrual. Each surviving account's raw amount is rounded half-up to integer cents exactly once, recorded as the row's `accrued_amount_cents`, with the bonus used recorded as `tier_bonus_bps_applied` and the row beginning ACCRUED; each row also carries its `declaration_id`. The declaration's `declared_pool_cents` is the sum of those per-account rounded amounts — the per-account rounding precedes the summation, never follows it.

Should the board reconsider, a `BoardDirector` may void a DECLARED declaration; voiding from any other state fails with `ERR_DECLARATION_INVALID_STATE`. Voiding moves every ACCRUED payment row of the declaration to VOIDED and touches no account balance — accrual is a computation, never a movement of money. VOIDED is terminal for the declaration.

Payment belongs to operations. An `OperationsOfficer` runs payment once the current clock date has reached the `payable_date`; an earlier attempt fails with `ERR_DIVIDEND_NOT_YET_PAYABLE`, and a declaration no longer DECLARED fails with `ERR_DECLARATION_INVALID_STATE`. The run recomputes every ACCRUED row from the account's full transaction history — including backdated rows posted after the declaration — using the pinned method and the member's tier as of the payment date. A row whose account is now CLOSED, or whose recomputed average end-of-day balance fails the 500-cent gate, moves to VOIDED. Every other row moves to CREDITED: `credited_amount_cents` holds the recomputed amount, `accrual_delta_cents` holds the credited amount minus the accrued amount — non-zero exactly when backdated transactions or tier changes intervened — `tier_bonus_bps_applied` reflects the payment-date bonus, and a SYSTEM ShareTransaction of kind DIVIDEND_CREDIT with `posted_date` set to the `payable_date` credits the account, raising its `balance_cents` and incrementing its `version`. The declaration's `paid_total_cents` — null until now — is set to the sum of `credited_amount_cents` over the CREDITED rows, the operator is recorded as `paid_by_user_id`, and the declaration becomes PAID, its terminal state. Payment rows can be reviewed per declaration, filterable by `status`, or per account.

### 3.8. Annual Meetings, Ballots, and the Reconvene Chain

Governance begins when a `BoardDirector` schedules the annual meeting with its `meeting_date`, the `record_date` that fixes voting eligibility, the `voting_open_date` on which ballots first open, and a `quorum_threshold` — a positive integer count of distinct voters. The dates must order correctly: the `record_date` strictly before the `voting_open_date`, and the `voting_open_date` on or before the `meeting_date`; any violation fails with `ERR_DATE_ORDER_INVALID`. Scheduling also observes a thirty-day spacing rule: a new meeting fewer than thirty days from another SCHEDULED or HELD meeting outside its reconvene chain is rejected with `ERR_MEETING_TOO_CLOSE`, while a gap of exactly thirty days is permitted and meetings within the same chain are exempt entirely. A new meeting begins SCHEDULED, and the meeting list can be filtered by `status` or by `reconvened_from_id` to trace a chain.

While a meeting is SCHEDULED, a `Member` casts a ballot by supplying the `meeting_id` and a `choice` of `FOR_SLATE_A`, `FOR_SLATE_B`, or `ABSTAIN`; the ballot's `member_id` is the caller's own `X-User-ID` and its `cast_date` is the current clock date. Checks run meeting-first: casting against a meeting that is not SCHEDULED fails with `ERR_MEETING_INVALID_STATE`, and only then is the voter examined — the member must be ACTIVE and their `membership_effective_date` must be on or before the meeting's `record_date`, and failing either condition yields `ERR_MEMBER_NOT_ELIGIBLE_TO_VOTE`. Ballots are accepted only within the voting window from `voting_open_date` through `meeting_date`, both days inclusive; a cast outside it fails with `ERR_VOTING_WINDOW_CLOSED`. One member, one ballot, per reconvene chain: a member who has already cast on any meeting of the chain is rejected with `ERR_BALLOT_ALREADY_CAST_IN_CHAIN`. Ballots are immutable once cast.

Closing the vote is a `BoardDirector` act that tallies the whole chain — the meeting itself plus every meeting reachable by following `reconvened_from_id` links backwards. The distinct-voter count is the number of distinct `member_id` values across all ballots cast on any meeting in the chain; because ballots are immutable, no status filtering applies. When that count is at least the `quorum_threshold` — the exact boundary meets quorum — the meeting closes HELD with `quorum_met` recorded true; when it falls short, the meeting closes ADJOURNED_NO_QUORUM with `quorum_met` false, which is a recorded outcome rather than an error. Either way the tally snapshot is written to the tallied meeting: `ballots_counted` set to the distinct-voter count, `votes_for_slate_a` and `votes_for_slate_b` holding the chain-wide counts of each slate's ballots, and `votes_abstain` holding the abstentions, which count toward quorum but toward neither slate. The snapshot is immutable — later reconvenes never rewrite it — and tallying a meeting that is not SCHEDULED fails with `ERR_MEETING_INVALID_STATE`.

An adjourned meeting is terminal for voting but fertile: reconvening an ADJOURNED_NO_QUORUM meeting — any other state fails with `ERR_MEETING_INVALID_STATE` — creates a brand-new AnnualMeeting in SCHEDULED whose `reconvened_from_id` points at the adjourned meeting and which inherits its `record_date` and `quorum_threshold`, while the caller supplies a fresh `meeting_date` and `voting_open_date` and the thirty-day spacing rule is waived inside the chain. Ballots cast anywhere in the chain count toward the successor's quorum and tallies, so the chain loops — adjourn, reconvene, tally again — until quorum is finally met. Ballot lists are available per meeting, reflecting only that meeting's own ballots rather than the chain's, and per member.

### 3.9. Eligibility Reviews, Grace Periods, and Forced Closure

Ongoing eligibility enforcement starts when a `ComplianceOfficer` opens a review against a member; the endpoint accepts only the reason MANUAL_FLAG for its `reason`, while SEGMENT_RETIRED reviews arise solely from the amendment cascade of §3.2 with `flagged_by_user_id` recorded as 'system'. When the member is ACTIVE, the review is created OPEN, the flagger's `X-User-ID` is recorded, and the member moves to INELIGIBLE_UNDER_REVIEW. The same flagging is also accepted while the member is GRACE_PERIOD — there it changes nothing about the member's status or `grace_end_date`, leaving the review OPEN alongside the grace period as the entry point for a late cure. Against a member in any other posture the attempt fails with `ERR_MEMBER_NOT_ACTIVE`. A member's reviews can be listed and filtered by `status`.

Curing a review is the way back. The review must be OPEN — anything else fails with `ERR_REVIEW_INVALID_STATE` — the deciding officer's `X-User-ID` must differ from the review's `flagged_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`, and the member must currently be INELIGIBLE_UNDER_REVIEW or GRACE_PERIOD; any other member posture also fails with `ERR_REVIEW_INVALID_STATE`, never with `ERR_MEMBER_NOT_ACTIVE`. A successful cure moves the review to CURED — terminal — records the decider as `decided_by_user_id`, returns the member to ACTIVE, clears `grace_end_date` to null if it was set, and preserves an optional `resolution_note`.

Confirming ineligibility is the way forward. It requires the same OPEN review, the same segregation of duties, and additionally that the member be INELIGIBLE_UNDER_REVIEW — confirming against any other member posture fails with `ERR_REVIEW_INVALID_STATE`. Confirmation moves the review to CONFIRMED_INELIGIBLE — terminal — moves the member to GRACE_PERIOD, and sets `grace_end_date` to ninety days after the current clock date: the member's statutory window to cure.

A CONFIRMED_INELIGIBLE review can never itself be cured, so the late cure within grace takes a deliberate two-step: a fresh manual review is opened while the member is GRACE_PERIOD — accepted without disturbing the member's posture, per above — and that new review is immediately cured, which clears the `grace_end_date` and restores the member to ACTIVE. The original confirmed review remains untouched in its terminal state.

When the grace window lapses, the clock does the closing. As the epoch sweep finds a GRACE_PERIOD member whose `grace_end_date` has been reached, the member becomes CLOSED_INELIGIBLE — terminal — and the cascade winds the relationship down: the member's OPEN share accounts are walked from the oldest `opened_date` forward, each account is CLOSED with closure reason FORCED_INELIGIBILITY, a SYSTEM ShareTransaction of kind CLOSURE_DISBURSEMENT for the full balance is posted on the current date so the account's `balance_cents` falls to zero, and every ACTIVE ProductEnrollment funded by such an account is closed with closure reason FORCED_ACCOUNT_CLOSURE. The member's `version` increments with the closure.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — a charter, an amendment application, a membership application, a share account, a transaction, an enrollment, a dividend declaration, an annual meeting, a reconvened successor meeting, a ballot, or an eligibility review — return `201 Created`. Operations that read a resource, modify an existing resource, or drive an action on it (approvals, denials, closures, tallies, payment runs, clock sets) return `200 OK`. Request payloads, computed fields, and side effects are defined by the workflows of §3; this table is the routing and authorization contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock and run the epoch sweep | SystemAdmin |
| POST | `/credit-union/charters` | Create the singleton charter with its initial segments | BoardDirector |
| GET | `/credit-union/charters/{id}` | Read a charter (includes `version` for OCC baselining) | MembershipOfficer, ComplianceOfficer, Regulator, BoardDirector, OperationsOfficer |
| GET | `/credit-union/charters/{id}/segments` | List a charter's eligibility segments | MembershipOfficer, ComplianceOfficer, Regulator, BoardDirector, OperationsOfficer |
| GET | `/credit-union/charters/{id}/amendment-applications` | List amendment applications for a charter | MembershipOfficer, ComplianceOfficer, Regulator, BoardDirector, OperationsOfficer |
| POST | `/credit-union/charter-amendment-applications` | File a charter amendment application (OCC-guarded) | ComplianceOfficer |
| POST | `/credit-union/charter-amendment-applications/{id}/approve` | Approve a submitted amendment application | Regulator |
| POST | `/credit-union/charter-amendment-applications/{id}/deny` | Deny a submitted amendment application | Regulator |
| POST | `/credit-union/membership-applications` | File a membership application | MembershipOfficer |
| GET | `/credit-union/membership-applications` | List membership applications | MembershipOfficer, ComplianceOfficer |
| GET | `/credit-union/membership-applications/{id}` | Read a membership application | MembershipOfficer, ComplianceOfficer |
| POST | `/credit-union/membership-applications/{id}/request-documents` | Request additional documents from the applicant | MembershipOfficer |
| POST | `/credit-union/membership-applications/{id}/submit-documents` | Submit supplemental documents | MembershipOfficer |
| POST | `/credit-union/membership-applications/{id}/approve` | Approve the application and create the member | MembershipOfficer |
| POST | `/credit-union/membership-applications/{id}/deny` | Deny the application | MembershipOfficer |
| GET | `/credit-union/members` | List members | MembershipOfficer, ComplianceOfficer, Regulator, BoardDirector, OperationsOfficer, Member |
| GET | `/credit-union/members/{id}` | Read a member (Member role: own record only) | MembershipOfficer, ComplianceOfficer, Regulator, BoardDirector, OperationsOfficer, Member |
| PATCH | `/credit-union/members/{id}` | Update member contact fields (OCC-guarded) | MembershipOfficer |
| POST | `/credit-union/members/{id}/tier-review` | Re-evaluate and materialize the member's tier | OperationsOfficer |
| POST | `/credit-union/share-accounts` | Open a share account | MembershipOfficer |
| GET | `/credit-union/share-accounts/{id}` | Read a share account | MembershipOfficer, ComplianceOfficer, Regulator, BoardDirector, OperationsOfficer, Member |
| GET | `/credit-union/members/{id}/share-accounts` | List a member's share accounts | MembershipOfficer, ComplianceOfficer, Regulator, BoardDirector, OperationsOfficer, Member |
| POST | `/credit-union/share-accounts/{id}/close` | Close an open share account | MembershipOfficer |
| POST | `/credit-union/share-accounts/{id}/transactions` | Post a deposit or withdrawal | OperationsOfficer |
| GET | `/credit-union/share-accounts/{id}/transactions` | List an account's transactions in replay order | MembershipOfficer, ComplianceOfficer, Regulator, BoardDirector, OperationsOfficer, Member |
| GET | `/credit-union/share-accounts/{id}/dividend-payments` | List dividend payment rows for an account | MembershipOfficer, ComplianceOfficer, Regulator, BoardDirector, OperationsOfficer, Member |
| POST | `/credit-union/product-enrollments` | Enroll a member in a tier-gated product | MembershipOfficer |
| GET | `/credit-union/product-enrollments` | List product enrollments | MembershipOfficer, ComplianceOfficer, Regulator, BoardDirector, OperationsOfficer |
| GET | `/credit-union/product-enrollments/{id}` | Read a product enrollment | MembershipOfficer, ComplianceOfficer, Regulator, BoardDirector, OperationsOfficer |
| POST | `/credit-union/dividend-declarations` | Declare a dividend and run provisional accrual | BoardDirector |
| GET | `/credit-union/dividend-declarations/{id}` | Read a dividend declaration | MembershipOfficer, ComplianceOfficer, Regulator, BoardDirector, OperationsOfficer |
| POST | `/credit-union/dividend-declarations/{id}/void` | Void a declared dividend | BoardDirector |
| POST | `/credit-union/dividend-declarations/{id}/pay` | Run the dividend payment | OperationsOfficer |
| GET | `/credit-union/dividend-declarations/{id}/payments` | List a declaration's payment rows | MembershipOfficer, ComplianceOfficer, Regulator, BoardDirector, OperationsOfficer |
| POST | `/credit-union/annual-meetings` | Schedule an annual meeting | BoardDirector |
| GET | `/credit-union/annual-meetings` | List annual meetings | MembershipOfficer, ComplianceOfficer, Regulator, BoardDirector, OperationsOfficer |
| GET | `/credit-union/annual-meetings/{id}` | Read an annual meeting | MembershipOfficer, ComplianceOfficer, Regulator, BoardDirector, OperationsOfficer, Member |
| POST | `/credit-union/annual-meetings/{id}/close-and-tally` | Close voting and tally the reconvene chain | BoardDirector |
| POST | `/credit-union/annual-meetings/{id}/reconvene` | Reconvene an adjourned meeting as a successor | BoardDirector |
| POST | `/credit-union/ballots` | Cast a ballot on a meeting | Member |
| GET | `/credit-union/annual-meetings/{id}/ballots` | List ballots cast on a meeting | MembershipOfficer, ComplianceOfficer, Regulator, BoardDirector, OperationsOfficer |
| GET | `/credit-union/members/{id}/ballots` | List a member's ballots | MembershipOfficer, ComplianceOfficer, Regulator, BoardDirector, OperationsOfficer, Member |
| POST | `/credit-union/members/{id}/eligibility-reviews` | Open a manual eligibility review on a member | ComplianceOfficer |
| GET | `/credit-union/members/{id}/eligibility-reviews` | List a member's eligibility reviews | MembershipOfficer, ComplianceOfficer, Regulator, BoardDirector, OperationsOfficer |
| POST | `/credit-union/eligibility-reviews/{id}/cure` | Cure an open eligibility review | ComplianceOfficer |
| POST | `/credit-union/eligibility-reviews/{id}/confirm-ineligible` | Confirm ineligibility and start the grace period | ComplianceOfficer |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them in §2 and §3; this catalogue is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_TIER_REQUIREMENT_NOT_MET` | 403 Forbidden |
| `ERR_MEMBER_NOT_ELIGIBLE_TO_VOTE` | 403 Forbidden |
| `ERR_VALIDATION_FAILED` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_CHARTER_VERSION` | 412 Precondition Failed |
| `ERR_STALE_MEMBER_VERSION` | 412 Precondition Failed |
| `ERR_MEMBER_NOT_ACTIVE` | 409 Conflict |
| `ERR_ACCOUNT_NOT_OPEN` | 409 Conflict |
| `ERR_APPLICATION_INVALID_STATE` | 409 Conflict |
| `ERR_AMENDMENT_INVALID_STATE` | 409 Conflict |
| `ERR_DECLARATION_INVALID_STATE` | 409 Conflict |
| `ERR_MEETING_INVALID_STATE` | 409 Conflict |
| `ERR_REVIEW_INVALID_STATE` | 409 Conflict |
| `ERR_SEGMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_CHARTER_ALREADY_EXISTS` | 409 Conflict |
| `ERR_PRIMARY_ACCOUNT_EXISTS` | 409 Conflict |
| `ERR_PRIMARY_ACCOUNT_REQUIRED` | 409 Conflict |
| `ERR_ALREADY_ENROLLED` | 409 Conflict |
| `ERR_BALLOT_ALREADY_CAST_IN_CHAIN` | 409 Conflict |
| `ERR_DIVIDEND_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_MEETING_TOO_CLOSE` | 409 Conflict |
| `ERR_VOTING_WINDOW_CLOSED` | 409 Conflict |
| `ERR_DIVIDEND_NOT_YET_PAYABLE` | 409 Conflict |
| `ERR_DOCUMENTATION_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_SPONSOR_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_PRODUCT_FUNDING_ACCOUNT_INVALID` | 422 Unprocessable Entity |
| `ERR_BOND_TYPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DIVIDEND_RATE_OUT_OF_BAND` | 422 Unprocessable Entity |
| `ERR_EFFECTIVE_DATE_NOT_FUTURE` | 422 Unprocessable Entity |
| `ERR_DATE_ORDER_INVALID` | 422 Unprocessable Entity |
| `ERR_INVALID_TRANSACTION_DATE` | 422 Unprocessable Entity |
| `ERR_BELOW_PAR_VALUE` | 422 Unprocessable Entity |
| `ERR_PAR_VALUE_BREACH` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_FUNDS` | 422 Unprocessable Entity |
