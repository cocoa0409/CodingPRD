# Property Tax Assessment & Appeal API — Product Requirements Document

## 1. Introduction

County assessment offices carry a peculiar tension at their heart: the same parcel must be valued two fundamentally different ways depending on a single historical fact. In a stable year, the law protects the homeowner by clamping how fast the taxable base may rise — a Proposition-13-style guardrail that lets a long-held home drift far below its hot-market worth. But the moment a property changes hands or new construction is added, that protection evaporates and the parcel snaps back to full market value, resetting the clock for everyone who follows. This API exists to make that divergence auditable rather than accidental: every assessment records *why* its base was capped or rebased, and the resulting number flows deterministically into exemptions, the tax bill, the appeal that may contest it, and the deferral ledger that may postpone it.

The system models the full annual cycle and the adversarial machinery layered on top of it. An assessor opens a tax roll for the year, drafts a per-parcel assessment, notices it to the owner, and finalizes it into a bill. A taxpayer who believes the number is wrong files an appeal with the Board of Equalization, which is a genuine negotiation — rounds of counter-offers and evidence, a scheduled hearing, and a decision that may settle in the middle, grant the petition outright, or deny it. Because the assessor who set a value must not be the officer who judges the challenge to it, the platform enforces a strict segregation of duties between the people who value, the people who review exemptions, and the people who hear appeals. Finally, qualifying senior and disability owners may defer their bills against a lien that accrues simple interest on the declining principal, with payments applied through a fixed waterfall. The contracts below specify each of these mechanisms precisely enough that two independent implementations would produce identical numbers from identical inputs.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request other than owner self-registration and the public list endpoints must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. The `X-User-Role` header must name one of exactly five roles — `Assessor`, `Reviewer`, `HearingOfficer`, `Taxpayer`, or `Anonymous`. When either header is missing or unrecognized on a protected endpoint, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are valid but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403). The authorized roles for each endpoint are listed in §4.

The five roles divide responsibility as follows. An `Assessor` is county staff who creates tax rolls, parcels, and assessments, drives them through their lifecycle, issues bills, and administers deferrals. A `Reviewer` adjudicates exemption claims and does nothing else of consequence. A `HearingOfficer` is a Board of Equalization officer who schedules and holds hearings and decides appeals. A `Taxpayer` is the property owner: they claim exemptions, file and withdraw appeals, submit evidence, and pay deferrals on parcels they own. An `Anonymous` caller can do exactly one thing — register themselves as an owner.

Identity binding differs by role and is critical to ownership checks. When `X-User-Role` is `Taxpayer`, the role is **entity-backed**: `X-User-ID` is the `id` of the acting `Owner`, and ownership checks compare the targeted resource's owner foreign key to `X-User-ID`. Concretely, when a taxpayer submits evidence on or withdraws an appeal, their `X-User-ID` must equal that appeal's `filed_by_owner_id`; when a taxpayer pays a deferral, their `X-User-ID` must match the relevant `owner_id`. A mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). The other four roles — `Assessor`, `Reviewer`, `HearingOfficer`, and `Anonymous` — are **opaque**: their `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record such an identifier where a workflow calls for it (for instance, a hearing stores the assigned officer's id in `hearing_officer_role_user_id`, and the segregation-of-duties check compares the accepting officer's `X-User-ID` against the operator id that earlier noticed the assessment), but it never equates an opaque id to any entity's `id`.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter defaults to 0 and is the count of records skipped from the front of the result set. Every list is sorted by `created_at` in ascending order before the window is applied, so paging is stable across requests. Each list response carries `limit`, `offset`, `total_count`, and `has_more` inside its `meta` object, where `total_count` is the size of the full filtered set and `has_more` is true exactly when records remain beyond the current window.

### 2.4. Common Resource Properties and Versioning

Every resource is identified by an `id` that is a server-minted UUID carrying no type prefix. Most resources also expose three system-managed fields: `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits, and `version` is an integer that begins at 1 on creation and increments by 1 on every mutation of that resource. Whenever a field on a resource changes, its `updated_at` is refreshed and its `version` advances. The entities that carry this full set are `TaxRoll`, `Owner`, `Parcel`, `Assessment`, `Exemption`, `Appeal`, `BoardPanel`, `Hearing`, `DeferralAgreement`, and `TaxBill`. Each of those entities except `Owner` also exposes a system-managed `status` enum that tracks its lifecycle state; the permitted values for each are enumerated in §3. The one exception to the common-field set is `DeferralPayment`, which is an immutable append-only event: it carries only `id` and `created_at`, and has neither `updated_at` nor `version` because it is never modified once written.

### 2.5. Monetary Precision and Rounding Conventions

The system speaks two units of money, and the boundary between them matters. Valuations — market value, capped base, assessed value, exemption deductions, and taxable values — are carried in **whole dollars**: every computed dollar figure is rounded half-up to the nearest integer dollar. Ledger amounts on a deferral — principal, accrued interest, outstanding balance, payments, and the billed tax itself — are carried in **integer cents**. Where a cents figure is derived from a product (interest accrual, the tax bill), the full-precision product is computed first and rounded half-up to the nearest whole cent exactly once at the end; intermediate values are never truncated. Payment waterfall splits are already in cents and require no rounding.

### 2.6. Nested Resource Retrieval and Path Validation

Several read endpoints are nested under a parent — for example, the assessments of a parcel, the exemptions of an assessment, the hearings of an appeal or a panel, and the payments of a deferral. For any such path, the path parameters are resolved left to right: the parent named earliest in the path is verified to exist first, and only then is the child collection or descendant resolved. Any referenced `id` that does not resolve to a stored resource — whether in the path or the request body — yields `ERR_NOT_FOUND` (HTTP 404), and existence is always checked before any state or business rule. A sale that names a `new_owner_id` resolving to no `Owner` is the one place this surfaces under a distinct code, `ERR_OWNER_NOT_FOUND` (HTTP 404).

### 2.7. Optimistic Concurrency on Supersede Writes

Two write operations carry a version guard so that a client cannot act on a stale view of a parent it has not re-read. Filing an appeal must carry `expected_assessment_version`, which must equal the current `version` of the target `Assessment`. Because filing an appeal drives that assessment from `NOTICED` to `UNDER_APPEAL` and advances its `version`, a second filing that still carries the previously observed version is working from a stale view and is rejected with `ERR_STALE_VERSION` (HTTP 412) before the open-appeal state check is ever reached. Likewise, applying a deferral payment must carry `expected_deferral_version`, which must equal the current `version` of the target `DeferralAgreement`; because each applied payment waterfalls against the live balance and advances the agreement's `version`, a payment carrying a stale version was computed against an outdated balance and is rejected with `ERR_STALE_VERSION` (HTTP 412). This version comparison is evaluated **before** any state precondition on these two operations, so a stale write loses with a 412 rather than being masked by a downstream state error. No other endpoint takes a version field.

### 2.8. Validation Ordering

When several checks guard one endpoint, they are evaluated in a fixed precedence so that the reported error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then role authorization (`ERR_UNAUTHORIZED`), then — on appeal acceptance — segregation of duties (`ERR_SEGREGATION_OF_DUTIES`). Next, referenced resources are confirmed to exist (`ERR_NOT_FOUND`), then taxpayer resource-ownership (`ERR_NOT_RESOURCE_OWNER`). For the two version-guarded writes, the optimistic-concurrency check (`ERR_STALE_VERSION`) comes next, ahead of all state checks. State preconditions follow: the generic transition-allowed check (`ERR_INVALID_STATE`), then the roll-open, open-appeal, held-hearing, and assessments-final state gates. Business-referential rules — sale reassessment and prior-roll certification — follow, then the business constraints (exemption eligibility, duplicate exemption, panel-slot conflict, maximum rounds, settlement range, payment-exceeds-balance). Last of all, generic request-body schema validation (`ERR_INVALID_REQUEST`, HTTP 400) catches malformed payloads: a missing required field, a bad enum value, or an out-of-range numeric.

## 3. Business Logic & Workflows

### 3.1. The Annual Tax Roll

Each tax year is represented by a roll the assessor creates with a `tax_year` (an integer between 2000 and 2100, unique across all rolls), a `mill_rate` (mills charged per 1000 dollars of taxable value, at least 0 and carried to at most four decimal places), and a `growth_cap_pct` (the maximum year-over-year growth of a capped base, expressed as a fraction between 0 and 1 inclusive — 0.02 means two percent). The creator may also supply `prior_roll_id`, the id of the immediately preceding certified roll this one rolls forward from, and `senior_age_threshold`, the minimum owner age in years that qualifies for a senior exemption on this roll; when omitted, the senior age threshold defaults to 65. The genesis roll has no prior roll. A new roll begins in `DRAFT`.

A roll progresses `DRAFT → OPEN → CERTIFIED → CLOSED`, with `CLOSED` terminal. Opening a roll is permitted only when, if a `prior_roll_id` was given, that prior roll is itself `CERTIFIED`; otherwise the open is refused with `ERR_PRIOR_ROLL_NOT_CERTIFIED`. Certifying a roll is permitted only when every `Assessment` belonging to it has reached `FINAL`; if any assessment is not yet final, certification fails with `ERR_ASSESSMENTS_NOT_FINAL`. Certification is also the moment the ledger synchronizes to the parcels: for each assessment on the roll, its `capped_base_value` is copied into the corresponding `Parcel.last_certified_capped_base`, refreshing that parcel's `updated_at` and advancing its `version`, so that next year's cap computes from a freshly certified baseline. Closing a `CERTIFIED` roll is permitted only when a successor roll — one whose `prior_roll_id` equals this roll's `id` — already exists and is itself `CERTIFIED`; absent such a successor the close is refused with `ERR_NO_CERTIFIED_SUCCESSOR`. Rolls are listed in `created_at` order and may be filtered by `prior_roll_id`.

### 3.2. Owners and Parcels

An owner is registered with a legal `full_name`, a contact `email` that must be unique among owners, and a `birth_date` whose date portion drives the senior age test. Two optional attributes round out eligibility: `is_veteran`, a verified-veteran flag defaulting to false, and `disability_pct`, a service or medical disability rating between 0 and 100 that defaults to 0. Owner registration is the sole operation an anonymous caller may perform.

A parcel is the property itself and persists across tax years. It is created against an `owner_id` (the current owner of record), an `apn` (the assessor parcel number, unique among parcels), a `situs_address`, and an optional `is_primary_residence` flag that defaults to false and governs homestead eligibility. A parcel also carries `last_certified_capped_base`, a computed figure equal to the `capped_base_value` of its most recent certified assessment and serving as the baseline for next year's cap; it reads 0 before any certification. Parcels are listed in `created_at` order, filterable by `owner_id`, and begin life `ACTIVE`.

When a property changes hands the assessor records the sale by supplying the `new_owner_id` of the buyer, who must already exist as an owner — otherwise the sale is refused with `ERR_OWNER_NOT_FOUND`. Recording a sale moves the parcel from `ACTIVE` to `SOLD`, reassigns `owner_id` to the new owner, and resets `last_certified_capped_base` to 0 so the next year's assessment cannot inherit a stale cap. A sold parcel is a primed trigger: the very next assessment created for it must declare that it is rebasing because of the sale, and creating that assessment is what returns the parcel from `SOLD` to `ACTIVE`. The set of assessments and the set of deferral agreements belonging to a parcel are each retrievable as a list.

### 3.3. Drafting an Assessment and the Two Faces of Value

An assessment is the per-parcel, per-year valuation record, created by the assessor against a `parcel_id`, a `tax_roll_id`, and the appraiser-supplied `market_value` (the full market value for the year, at least 0). The creator may also supply `reassessment_event`, an enumeration of `NONE`, `SALE`, or `NEW_CONSTRUCTION` that defaults to `NONE` and decides which of two valuation regimes applies. A fresh assessment begins in `DRAFT`.

The choice between regimes is the system's defining calculation, computed at creation and again whenever the assessment is recomputed. Let the parcel's prior base be its `last_certified_capped_base` (which is 0 when the parcel has never been certified or was just rebased by a sale). When `reassessment_event` is `NONE` **and** the prior base is greater than 0, the parcel is rolling forward under the cap: the cap ceiling is the prior base multiplied by one plus the roll's `growth_cap_pct`, and `capped_base_value` is the smaller of the year's `market_value` and that ceiling. In a hot market the ceiling bites and the capped base lands well below market. When instead `reassessment_event` is `SALE` or `NEW_CONSTRUCTION`, **or** the prior base is 0 (the parcel's first-ever assessment), the cap is ignored entirely and `capped_base_value` is set to the full `market_value`, resetting the Proposition-13 base for all future years. In either regime `assessed_value` equals `capped_base_value`, and both are expressed in whole dollars, rounded half-up to the nearest dollar.

One referential rule guards assessment creation. If the parcel is currently `SOLD`, the assessment being created must carry `reassessment_event` equal to `SALE`; an attempt to create the post-sale assessment under any other event is rejected with `ERR_SALE_REASSESSMENT_REQUIRED` (HTTP 422). When a `SALE` assessment is created against a sold parcel, that parcel transitions from `SOLD` back to `ACTIVE` as a side effect of the create. Assessments are listed in `created_at` order and may be filtered by `tax_roll_id` and by `parcel_id`.

### 3.4. Exemptions: Claim, Adjudicate, Deduct

Against a `DRAFT` assessment, a taxpayer or assessor may claim an exemption by naming the parent `assessment_id` and an `exemption_type` of `HOMESTEAD`, `SENIOR`, `VETERAN`, or `DISABILITY`. The claim is born in `CLAIMED` status and carries a `claimed_amount` that is not yet meaningful until adjudication. A reviewer — and only a reviewer — then approves or denies each claim while the parent assessment is still `DRAFT`; an attempt to adjudicate against an assessment in any other state is refused with `ERR_INVALID_STATE`. Approval moves the exemption `CLAIMED → APPROVED`; denial moves it `CLAIMED → DENIED`; both are terminal.

Approval is the demanding branch and is guarded by two checks beyond the draft-state requirement. First, the owner or parcel must actually satisfy the claimed type's eligibility, or the approval is rejected with `ERR_EXEMPTION_INELIGIBLE`: a `HOMESTEAD` exemption requires the parcel's `is_primary_residence` to be true; a `SENIOR` exemption requires the owner's age, computed from `birth_date`, to be at least the roll's `senior_age_threshold`; a `VETERAN` exemption requires the owner's `is_veteran` flag to be true; and a `DISABILITY` exemption requires the owner's `disability_pct` to be at least 1. Second, no other exemption of the same `exemption_type` may already be `APPROVED` on that assessment, or the approval is rejected with `ERR_DUPLICATE_EXEMPTION`.

On approval the deduction is computed and recorded as `claimed_amount`, then folded into the parent assessment's running total. The deduction depends on the type. A homestead deduction is a flat 7,000 dollars. A veteran deduction is a flat 4,000 dollars. A senior deduction is the larger of a 5,000-dollar floor and ten percent of the assessment's `assessed_value` rounded half-up to whole dollars — that is, the senior amount never falls below 5,000 but rises with valuable homes. A disability deduction is the assessment's `assessed_value` multiplied by the owner's `disability_pct` divided by 100, then multiplied by a factor of one-half, the whole rounded half-up to whole dollars. In every case the per-exemption `claimed_amount` is finally clamped to no more than the assessment's `assessed_value`, since a single exemption can never wipe out more than the assessed value itself. Denial, by contrast, sets `claimed_amount` to 0 and leaves the assessment's running total untouched.

The deny branch is deliberately the lighter of the two: it requires only that the parent assessment be `DRAFT`, performs no eligibility or duplicate test, and its sole effect is to zero the claimed amount. The asymmetry is intentional — denial closes a claim without ever crediting it.

### 3.5. From Draft to Bill: Noticing and Finalizing

Noticing is the act of sending a drafted valuation to the owner, and it is the point at which the assessment's numbers are first composed into a taxable figure. Noticing is permitted only when the parent roll is `OPEN` — otherwise the notice is refused with `ERR_ROLL_NOT_OPEN` — and only when no exemption on the assessment is still `CLAIMED`; a lingering pending claim blocks the notice with `ERR_EXEMPTIONS_PENDING`. On a successful notice the assessment recomputes its values and moves `DRAFT → NOTICED`.

The taxable computation at notice is order-pinned and must be reproduced exactly. The `exemption_total` is the sum of the `claimed_amount` of every `APPROVED` exemption on the assessment — each of those amounts having been computed earlier against the *same* `assessed_value`, the value before any exemption was applied — and that raw sum is then clamped to no more than `assessed_value`. The system never subtracts one exemption and recomputes the next against a reduced base; all approved deductions share the single pre-exemption assessed value as their common basis, are summed, and only the total is clipped. The `taxable_value` is then the greater of 0 and `assessed_value` minus `exemption_total`. At notice the assessment also sets `final_taxable_value` equal to `taxable_value`; this is the figure the bill will eventually use unless an appeal later overrides it.

Finalizing freezes the assessment. It is permitted only when no appeal on the assessment is currently open — that is, none is in `FILED`, `UNDER_REVIEW`, or `EVIDENCE_REQUESTED` — otherwise the finalize is refused with `ERR_OPEN_APPEAL_EXISTS`. A successful finalize moves the assessment `NOTICED → FINAL`, which is terminal, and freezes `final_taxable_value` at its current value: the plain `taxable_value` if no appeal touched it, or the `appealed_value` an appeal resolution wrote into it.

### 3.6. The Board of Equalization Appeal

A taxpayer who contests a noticed valuation files an appeal naming the `assessment_id` under challenge, the `filed_by_owner_id` of the petitioner, the `requested_taxable_value` they ask the Board to set (at least 0), and `expected_assessment_version` carrying the assessment version they last observed. Filing requires the assessment to be `NOTICED`; the act creates the appeal in `FILED` and drives the assessment `NOTICED → UNDER_APPEAL`, advancing the assessment's `version` (see §2.7 for how that version guard forecloses a stale second filing). An appeal also tracks `opinion_of_value`, a working settlement target that defaults to the `requested_taxable_value` and is updated by Board counter-offers, and `round_no`, a negotiation-round counter that starts at 1. When the Board ultimately resolves the matter in the taxpayer's favor it records the result in `determined_taxable_value`, which stays null otherwise. Appeals are listed in `created_at` order and may be filtered by `assessment_id` and by `filed_by_owner_id`.

A `HearingOfficer` accepts a filed appeal into review, moving it `FILED → UNDER_REVIEW`. Acceptance requires the parent assessment to be in its `UNDER_APPEAL` state, and it enforces segregation of duties: the accepting officer's `X-User-ID` must differ from the operator id that noticed the parent assessment, or the acceptance is refused with `ERR_SEGREGATION_OF_DUTIES`. The negotiation then loops. The officer may request more evidence, moving the appeal `UNDER_REVIEW → EVIDENCE_REQUESTED` and recording the supplied `counter_value` as the new `opinion_of_value`; this is permitted only while `round_no` is below 3, and a request once `round_no` has reached 3 is refused with `ERR_MAX_ROUNDS_REACHED`. The petitioning taxpayer then submits evidence, moving the appeal `EVIDENCE_REQUESTED → UNDER_REVIEW` and incrementing `round_no` by 1; the submitting taxpayer's `X-User-ID` must equal the appeal's `filed_by_owner_id`. The cycle between `UNDER_REVIEW` and `EVIDENCE_REQUESTED` may thus repeat, bounded by the three-round ceiling.

From `UNDER_REVIEW` the Board reaches one of three decisions, and the resolutions are deliberately not symmetric. A **settlement** moves the appeal `UNDER_REVIEW → SETTLED` at an officer-supplied `settled_value`; that value must lie between the `requested_taxable_value` (inclusive) and the assessment's current `taxable_value` (inclusive), and a value outside that closed range is rejected with `ERR_SETTLEMENT_OUT_OF_RANGE`. On settlement `determined_taxable_value` is set to `settled_value`. A **grant** moves the appeal `UNDER_REVIEW → GRANTED` and sets `determined_taxable_value` to the full `requested_taxable_value`, awarding the petition in its entirety. A **denial** moves the appeal `UNDER_REVIEW → DENIED` and leaves `determined_taxable_value` null. Both grant and deny require that a hearing on this appeal has already been held — a hearing in `HELD` status — and either decision attempted without one is refused with `ERR_NO_HELD_HEARING`. Settlement carries no such hearing requirement. A taxpayer may also abandon the contest by withdrawing it, which moves the appeal to `WITHDRAWN`; withdrawal is available both from `FILED` and from `UNDER_REVIEW`, and the withdrawing taxpayer's `X-User-ID` must equal the appeal's `filed_by_owner_id`. The four terminal outcomes are `SETTLED`, `GRANTED`, `DENIED`, and `WITHDRAWN`.

Every appeal resolution releases the parent assessment from its `UNDER_APPEAL` hold back to `NOTICED`, but along two distinct branches. When the appeal ends `SETTLED` or `GRANTED`, the value-lowering branch fires: the assessment's `appealed_value` is set to the appeal's `determined_taxable_value`, and its `final_taxable_value` is overwritten with that same determined value, so the bill will reflect the Board's decision rather than the original taxable value. When the appeal ends `DENIED` or `WITHDRAWN`, the no-change branch fires: `appealed_value` stays null and `final_taxable_value` remains the original `taxable_value`. In both branches the assessment returns to `NOTICED`, where it can finally be finalized.

### 3.7. Scheduling and Holding Hearings

A `HearingOfficer` schedules hearings on board panels. A panel is created by the assessor with a `name` (a Board of Equalization panel label) and an optional `setup_buffer_minutes`, the mandatory clearance gap required after each hearing on that panel before the next may begin, defaulting to 15. A hearing is scheduled against an `appeal_id`, a `board_panel_id`, the `hearing_officer_role_user_id` of the officer assigned (recorded as an opaque operator id), and a half-open time window `starts_at` (inclusive) through `ends_at` (exclusive, and required to be strictly after `starts_at`). A new hearing is born `SCHEDULED`.

Scheduling is guarded against double-booking a panel. A new slot may not overlap any existing `SCHEDULED` or `HELD` hearing on the same panel, where each existing hearing is treated as occupying its half-open window from `starts_at` up to `ends_at` plus the panel's `setup_buffer_minutes` of clearance afterward; a proposed slot that intrudes on any such occupied-plus-buffer interval is rejected with `ERR_PANEL_SLOT_CONFLICT`. Cancelling a hearing moves it `SCHEDULED → CANCELLED` and frees its slot, so a previously conflicting reschedule can then succeed. Holding a hearing moves it `SCHEDULED → HELD`; this requires the parent appeal to be `UNDER_REVIEW`, and the officer marking it held must be the one assigned to it — their `X-User-ID` must equal the hearing's `hearing_officer_role_user_id`, or the hold is refused with `ERR_NOT_RESOURCE_OWNER`. Holding the hearing is the prerequisite that unlocks the grant and deny decisions in §3.6. Both `HELD` and `CANCELLED` are terminal. The hearings on a given appeal, and the hearings on a given panel, are each retrievable as a list.

### 3.8. Issuing and Paying the Bill

Once an assessment is `FINAL`, the assessor issues its tax bill. The bill snapshots `billed_taxable_value` from the assessment's `final_taxable_value` at the moment of issuance and computes `tax_amount_cents` with a pinned rounding order: the full-precision product of the billed taxable value and the roll's `mill_rate` divided by 1000 is taken first as a dollar figure, then converted to cents, and only then rounded half-up to a whole cent — a single rounding applied once, after the complete product. (Equivalently, the cents amount is the billed taxable value times the mill rate divided by 10, rounded half-up.) A newly issued bill is `ISSUED`, its `is_deferred` flag false. The bills belonging to an assessment are retrievable as a list.

A taxpayer (or the assessor on their behalf) may pay an issued bill in full, moving it `ISSUED → PAID`; a bill that is already `PAID` or `DEFERRED` cannot be paid again and the attempt is refused with `ERR_INVALID_STATE`. The alternative to paying is deferral, covered next. Both `PAID` and `DEFERRED` are terminal.

### 3.9. Deferral Agreements, Accrual, and the Payment Waterfall

A qualifying owner may postpone their taxes under a deferral agreement the assessor opens against a `parcel_id`, the `owner_id` granted the deferral (who must be senior- or disability-eligible), and an `annual_interest_rate` (a simple annual rate between 0 and 1 inclusive). The agreement tracks four cents-denominated ledger figures: `deferred_principal_cents`, the cumulative principal deferred; `accrued_interest_cents`, the cumulative interest assessed; `total_paid_cents`, the sum of applied payments; and `outstanding_balance_cents`, which always equals `deferred_principal_cents` plus `accrued_interest_cents` minus `total_paid_cents`. A new agreement is `ACTIVE`. Deferrals are listed in `created_at` order, filterable by `parcel_id` and by `owner_id`.

Principal enters the agreement by enrolling bills. The assessor rolls an `ISSUED` bill into the deferral by supplying its `tax_bill_id`; the bill must be `ISSUED` and not already enrolled, or the enrollment is refused with `ERR_INVALID_STATE`. Enrollment moves the bill `ISSUED → DEFERRED`, sets its `is_deferred` to true, adds that bill's `tax_amount_cents` to the agreement's `deferred_principal_cents`, and recomputes `outstanding_balance_cents`.

Interest accrues one annual period at a time when the assessor runs an accrual on the agreement. The sanctioned method is a **declining-balance** accrual: interest is charged only on principal not yet repaid, never on principal already paid down. Concretely, the outstanding principal is `deferred_principal_cents` minus the principal that prior payments have already retired; the period's interest is that outstanding principal multiplied by the `annual_interest_rate`, rounded half-up to a whole cent; this period interest is added to `accrued_interest_cents`, and `outstanding_balance_cents` is recomputed. Because the base shrinks as principal is repaid, each successive accrual after a principal-reducing payment charges less than it otherwise would.

Payments are append-only events applied through a fixed interest-first waterfall. A payment records its `deferral_agreement_id` and an `amount_cents` of at least 1, and must carry `expected_deferral_version` matching the agreement's current `version` (the stale-version guard of §2.7). The split is computed against the live ledger: the remaining unpaid interest is the difference between `accrued_interest_cents` and the interest already covered by earlier payments, and `applied_to_interest_cents` is the smaller of the payment's `amount_cents` and that remaining interest. Whatever of the payment is left after interest is `applied_to_principal_cents`, capped at the principal not yet retired. The interest bucket is always exhausted before any cent touches principal, so a partial payment never reduces principal while interest remains. The applied interest and applied principal are then added to `total_paid_cents` and `outstanding_balance_cents` is recomputed. A payment whose `amount_cents` would carry the agreement past a zero balance — that is, an overpayment beyond the full outstanding balance — is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE` rather than refunded. When an applied payment brings `outstanding_balance_cents` to exactly 0, the agreement automatically moves `ACTIVE → SATISFIED` and its lien is released.

A deferral may instead end in default. When a parcel under deferral has been sold — its parcel status is `SOLD` — the assessor may declare the agreement defaulted, moving it `ACTIVE → DEFAULTED` and rendering `outstanding_balance_cents` immediately due; declaring default while the parcel is not sold is refused with `ERR_INVALID_STATE`. Both `SATISFIED` and `DEFAULTED` are terminal. The payments applied to an agreement are retrievable as a list.

## 4. Endpoint Definitions

All endpoints share the response envelope of §2.2. Creating a new resource returns HTTP 201; fetching, listing, and state-changing operations on an existing resource return HTTP 200. Request and response bodies are not tabulated here — reconstruct them from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | `/owners` | Register a property owner | Assessor, Anonymous |
| GET | `/owners/{id}` | Fetch an owner | Assessor, Reviewer, HearingOfficer, Taxpayer |
| POST | `/tax-rolls` | Create a tax-year roll | Assessor |
| GET | `/tax-rolls` | List tax rolls (filterable by prior_roll_id) | Assessor, Reviewer, HearingOfficer |
| GET | `/tax-rolls/{id}` | Fetch a tax roll | Assessor, Reviewer, HearingOfficer |
| POST | `/tax-rolls/{id}/open` | Open a DRAFT roll | Assessor |
| POST | `/tax-rolls/{id}/certify` | Certify an OPEN roll | Assessor |
| POST | `/tax-rolls/{id}/close` | Close a CERTIFIED roll | Assessor |
| POST | `/parcels` | Create a parcel | Assessor |
| GET | `/parcels` | List parcels (filterable by owner_id) | Assessor, Reviewer, HearingOfficer |
| GET | `/parcels/{id}` | Fetch a parcel | Assessor, Reviewer, HearingOfficer, Taxpayer |
| POST | `/parcels/{id}/record-sale` | Record a sale: reassign owner and rebase the cap | Assessor |
| GET | `/parcels/{id}/assessments` | List assessments for a parcel | Assessor, Reviewer, HearingOfficer, Taxpayer |
| GET | `/parcels/{id}/deferrals` | List deferral agreements for a parcel | Assessor, Reviewer, Taxpayer |
| POST | `/assessments` | Create a per-parcel per-roll assessment | Assessor |
| GET | `/assessments` | List assessments (filterable by tax_roll_id and parcel_id) | Assessor, Reviewer, HearingOfficer |
| GET | `/assessments/{id}` | Fetch an assessment | Assessor, Reviewer, HearingOfficer, Taxpayer |
| POST | `/assessments/{id}/notice` | Notice a DRAFT assessment | Assessor |
| POST | `/assessments/{id}/finalize` | Finalize a NOTICED assessment | Assessor |
| POST | `/assessments/{id}/issue-bill` | Issue the tax bill for a FINAL assessment | Assessor |
| GET | `/assessments/{id}/exemptions` | List exemptions on an assessment | Assessor, Reviewer, HearingOfficer, Taxpayer |
| GET | `/assessments/{id}/appeals` | List appeals on an assessment | Assessor, Reviewer, HearingOfficer, Taxpayer |
| GET | `/assessments/{id}/bills` | List tax bills for an assessment | Assessor, Reviewer, Taxpayer |
| GET | `/tax-bills/{id}` | Fetch a tax bill | Assessor, Reviewer, Taxpayer |
| POST | `/tax-bills/{id}/pay` | Pay an ISSUED tax bill in full | Assessor, Taxpayer |
| POST | `/exemptions` | Claim an exemption against a DRAFT assessment | Assessor, Taxpayer |
| GET | `/exemptions/{id}` | Fetch an exemption | Assessor, Reviewer, Taxpayer |
| POST | `/exemptions/{id}/approve` | Approve a claimed exemption | Reviewer |
| POST | `/exemptions/{id}/deny` | Deny a claimed exemption | Reviewer |
| POST | `/appeals` | File an appeal against a NOTICED assessment | Taxpayer |
| GET | `/appeals` | List appeals (filterable by assessment_id and filed_by_owner_id) | Assessor, Reviewer, HearingOfficer, Taxpayer |
| GET | `/appeals/{id}` | Fetch an appeal | Assessor, Reviewer, HearingOfficer, Taxpayer |
| POST | `/appeals/{id}/accept` | Accept an appeal into review | HearingOfficer |
| POST | `/appeals/{id}/request-evidence` | Board counter-offer; request more evidence | HearingOfficer |
| POST | `/appeals/{id}/submit-evidence` | Submit evidence, return appeal to review | Taxpayer |
| POST | `/appeals/{id}/settle` | Settle the appeal at an agreed value | HearingOfficer |
| POST | `/appeals/{id}/grant` | Grant the petition in full | HearingOfficer |
| POST | `/appeals/{id}/deny` | Deny the petition | HearingOfficer |
| POST | `/appeals/{id}/withdraw` | Withdraw the appeal | Taxpayer |
| GET | `/appeals/{id}/hearings` | List hearings on an appeal | Assessor, Reviewer, HearingOfficer, Taxpayer |
| POST | `/board-panels` | Create a Board of Equalization panel | Assessor |
| GET | `/board-panels/{id}` | Fetch a board panel | Assessor, Reviewer, HearingOfficer |
| GET | `/board-panels/{id}/hearings` | List hearings on a panel | Assessor, Reviewer, HearingOfficer |
| POST | `/hearings` | Schedule a hearing slot on a panel | HearingOfficer |
| GET | `/hearings/{id}` | Fetch a hearing | Assessor, Reviewer, HearingOfficer, Taxpayer |
| POST | `/hearings/{id}/hold` | Mark a hearing HELD | HearingOfficer |
| POST | `/hearings/{id}/cancel` | Cancel a scheduled hearing | HearingOfficer |
| POST | `/deferrals` | Open a tax repayment deferral | Assessor |
| GET | `/deferrals` | List deferral agreements (filterable by parcel_id and owner_id) | Assessor, Reviewer, Taxpayer |
| GET | `/deferrals/{id}` | Fetch a deferral agreement | Assessor, Reviewer, Taxpayer |
| POST | `/deferrals/{id}/enroll-bill` | Roll an ISSUED bill into the deferral | Assessor |
| POST | `/deferrals/{id}/accrue-interest` | Run one annual interest accrual period | Assessor |
| POST | `/deferrals/{id}/payments` | Apply a payment via interest-first waterfall | Assessor, Taxpayer |
| POST | `/deferrals/{id}/default` | Declare a deferral defaulted | Assessor |
| GET | `/deferrals/{id}/payments` | List payments on a deferral | Assessor, Reviewer, Taxpayer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|------------------|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_OWNER_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ROLL_NOT_OPEN` | 409 |
| `ERR_PRIOR_ROLL_NOT_CERTIFIED` | 409 |
| `ERR_NO_CERTIFIED_SUCCESSOR` | 409 |
| `ERR_EXEMPTIONS_PENDING` | 409 |
| `ERR_OPEN_APPEAL_EXISTS` | 409 |
| `ERR_NO_HELD_HEARING` | 409 |
| `ERR_ASSESSMENTS_NOT_FINAL` | 409 |
| `ERR_DUPLICATE_EXEMPTION` | 409 |
| `ERR_PANEL_SLOT_CONFLICT` | 409 |
| `ERR_MAX_ROUNDS_REACHED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SALE_REASSESSMENT_REQUIRED` | 422 |
| `ERR_EXEMPTION_INELIGIBLE` | 422 |
| `ERR_SETTLEMENT_OUT_OF_RANGE` | 422 |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
