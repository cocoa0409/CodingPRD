# Worklog — task_1805_school_facility_use_community_rental

## Step 1: Create Task Directory — 2026-08-14T17:37:00.000Z

Directory `tasks/task_1805_school_facility_use_community_rental/` and `workspace/` created by the pipeline launcher (pre-done before this session; index 1805 assigned externally).

## Step 3: Copy Shared Files — 2026-08-14T17:38:15.703Z

Copied `./INSTRUCTION.md` → `tasks/task_1805_school_facility_use_community_rental/workspace/INSTRUCTION.md` (1424 bytes).

## Step 2: Generate Scaffold — 2026-08-14T18:35:24.969Z

All checks pass. The scaffold is complete and lint-clean.

### Files written
- `tasks/task_1805_school_facility_use_community_rental/SCAFFOLD.yaml` — §1.0–§1.7 (93 KB)
- `tasks/task_1805_school_facility_use_community_rental/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — `scaffold_difficulty_design:` only (102 KB)
- `tasks/task_1805_school_facility_use_community_rental/SCAFFOLD_CORNER_DESIGN.yaml` — `scaffold_corner_design:` only (168 KB)

### Counts
- **Entities**: 13 (SchoolSite, Facility, RenterOrganization, RateClassPolicy, SchoolCalendarEvent, RentalRequest, InsuranceCertificate, Permit, CustodialWorkOrder, Invoice, DamageAssessment, PaymentTransaction, SeasonalPermit)
- **State machines**: 12 (incl. cyclic revision loop on RentalRequest; parallel lifecycle × financial dimensions on Permit)
- **Calculations**: 9 (rental_charge_quote, staffing_charge, after_hours_charge, invoice_total, cancellation_refund, deposit_forfeiture_allocation, priority_conflict_resolution, insurance_coverage_sufficiency, seasonal_occurrence_expansion)
- **Validations**: 12 priority-ordered rows
- **Endpoints**: 69
- **Errors**: 25 (all referenced from §1.2/§1.4 — zero dead codes)
- **Roles**: 5 (RenterOrgRep entity-backed; SiteCoordinator, FacilitiesDirector, CustodialSupervisor, DistrictAdmin opaque; segregation-of-duties on damage intake vs adjudication)
- **§1.8 instances**: 18 (9 rules × 2, all differentiated per §0.5's clauses)
- **§1.9 instances**: 51 active + 2 `excluded_because:` stubs across all nine claim-extraction sections

### Notable design decisions (max-difficulty directive)
- **Archetype blend**: temporal windowing (half-open blocked intervals with setup/teardown buffers) × pricing engine × priority-allocation; segregation-of-duties role model.
- **Dual-variant pair on different domains**: Invoice money (provisional estimate vs verified actuals, delta 9975) vs Permit refund waterfall (tiered cancel 9650 vs ADMINISTRATIVE supersession 24300 on identical 24300 deposit).
- **Combinatorial modes (a), (b), (c) all exercised**: (c) discount tier re-keys on pre-discount subtotal with a pinned 7-step evaluation order, proven by a provisional→final tier crossing (144000→99000 subtotal flips 10%→5%); (b) per-component rounding pinned with a 1-cent discriminating fixture (8750 vs 8749 at custodial rate 3333 × 1.5h); (a) rate-class × tier × duration-block tiered pricing.
- **Boundary precision**: cancellation day-14 vs day-13 (14650-cent swing), insurance headcount 99 vs 100 tier flip, 60 vs 61-minute block rounding, 5.5h vs 6.0h rebate, min-shift floor at exactly 2.0h.
- **Temporal overlap with two interval semantics**: buffered half-open facility intervals (adjacency at the exclusive endpoint approved, 30-min overlap rejected) vs site-wide blackout aggregate overlap (null facility_id supersedes permits on every facility).
- **Transitive cascades**: damage FINAL → permit forfeiture → forfeiture_count → org SUSPENDED (depth 3); site close → facility RETIRED → requests WITHDRAWN (depth 2).
- **Compensating invariants**: permit money conservation (capture − refund − forfeit == 0) and renter-ledger conservation (issue/pay and damage shortfall split sum exactly).
- **OCC** on RentalRequest (approve supersede) and SeasonalPermit (renewal), all `expected_*_version` payloads bound to fresh `${var}` captures; a logical-clock test endpoint with pinned startup default `2026-08-01T00:00:00Z`.
- All formula-derived asserts are literals precomputed by executing the §1.3 formulas in Python during authoring.

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (817 calls scanned). No sibling task directories were inspected.

## Step 4: Generate PRD — 2026-08-14T18:53:21.206Z

Generation complete. Summary report:

**Output:** `tasks/task_1805_school_facility_use_community_rental/workspace/PRD.md` — 349 lines

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC (5 roles with identity translation), 2.2 API Response Structure (verbatim block, byte-identical incl. `req_RANDOMALPHANUM123456` / `2025-05-24T10:30:00.123Z` / `UNIQUE_ERROR_IDENTIFIER_STRING` / `"data": { }`), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), 2.4 Logical Clock & Interval Semantics (startup default 2026-08-01T00:00:00Z, half-open intervals, site-local day boundaries), 2.5 Common Resource Properties (incl. PaymentTransaction `common_fields: false` exception), 2.6 Nested Resource Retrieval (left-to-right), 2.7 Money/Cents/Rounding, 2.8 OCC (both rules, exact `ERR_STALE_VERSION`/412), 2.9 Validation Pipeline (12 tiers with explicit evaluation order and applies-to scopes), 2.10 Uniqueness & Idempotency
- §3 Business Logic (9 subsections): 3.1 Sites/Facilities/Calendar, 3.2 Rate Policies, 3.3 Renters/Standing/Insurance, 3.4 Request Pipeline, 3.5 Permits/Deposits/Payments, 3.6 Completion/Work Orders/Invoice Math, 3.7 Cancellation/Preemption/Refund Waterfall, 3.8 Damage/Forfeiture, 3.9 Seasonal Permits
- §4 Endpoint Definitions (4-column table), §5 Error Code Catalogue (2-column table)

**Coverage counts:** 13 entities, 12 state machines (all transitions expressed, from/to states named), 9 calculations (all formulas in reconstruction-safe prose, constants embedded — 30-min blocks, 6h/10% rebate, 2.0h minimum shift, 50%/25% additive uplift, 07:00–18:00 window, 50000/100000/200000 discount tiers, 14/7-day refund tiers, 2500-cent fee, insurance tiers at 100/500 headcount, 120-day season span), 12 validation priority tiers, 69 endpoints (69 table rows), 25 errors (25 table rows, all 25 also named in §2/§3 prose), 5 roles (all with identity semantics).

**Hard Contract audit results (all PASS):**
- Contract 1 Field-Name Coverage: 117 required (entity fields + endpoint inputs + query/path params + common fields + `current_utc`), 117 present, 0 missing — PASS
- Contract 2 Rule Coverage: 12/12 validation priorities expressed with ordering; 2/2 OCC rules (write endpoint + `expected_request_version`/`expected_series_version` + `ERR_STALE_VERSION`/412 all named, no race-framing); all state-machine transitions, calculations, validation conditions, endpoint side effects, field structured content expressed; sibling branches (cancellation tiers, insurance tiers, discount tiers, invoice kinds, priority classes, OCC pair) rendered with equal density — PASS
- Contract 3 §3 Path Purity: 529 backticked tokens scanned, 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos — PASS
- Additional checks: all 44 state enum values and 64 enum values backticked; pseudocode-operator scan clean; fuzzy-word scan clean; §2.2 verbatim block intact.

**Constraint compliance:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced; no sibling task under `tasks/` was inspected. The PRD was generated solely from this task's `SCAFFOLD.yaml` plus the doc-generator skill specification (including its `section-2.2-response-structure.md` verbatim source and `example-prd.md` style reference).

## Resume Assessment — 2026-08-14T19:20:00.000Z

Prior run terminated mid-Step-5 (no Step 5/6 worklog entries). Artifact audit:
- Steps 1-4: complete and valid (SCAFFOLD.yaml + both design indices; INSTRUCTION.md; PRD.md 349 lines).
- Step 5 test suite: **INCOMPLETE** — all files compile, but only 20 tests covering 10/18 §1.8 difficulty instances; 0/51 active §1.9 corner instances emitted. Missing difficulty instances: staffing_round_per_component_then_sum, insurance_headcount_tier_100_boundary, permit_activation_gated_on_financial_dimension, work_order_verify_gated_on_permit_completion, facility_blocked_interval_half_open_adjacency, site_wide_blackout_aggregate_overlap, deposit_capture_refund_forfeit_conservation, invoice_accrual_pay_and_damage_shortfall_conservation. → Re-running Step 5 in completion mode (audit + keep conforming tests, generate missing coverage).
- Step 6 implementation: structurally complete — 3136 lines, all files compile, 69 route decorators registered (matches PRD's 69 endpoints), boots cleanly on $PORT/0.0.0.0 and serves JSON envelope. Kept as-is; Step 7 will validate behaviorally.

## Step 5: Generate Unit Tests (completion run) — 2026-08-14T19:55:00.000Z

Resumed from the mid-flight termination noted above. Audited the 9 existing test_helpers/ files and 10 existing test files (20 tests): all conform (design-index-only sourcing, verbatim PRD citations, single resolving `Design:` tag per test, entity-backed identity threading correct). Kept all 20.

Extended test_helpers/fixtures.py additively (add_renter_with_insurance, make_approved_permit_in_env, make_calendar_event, pay_fee, get_single_work_order, complete_permit_at) — no existing import broken.

New tests emitted: queue A +14 (7 files, test_11..test_17), queue B +53 test functions across 13 files (test_20..test_32) covering all 51 active §1.9 instances. Suite totals: 88 collected tests; every test carries exactly one resolving `Design:` tag and a verbatim PRD citation (mechanically audited: all tags resolve against the two indices; every quoted segment has a >=8-word contiguous substring present in PRD.md; no skip/xfail markers).

Skipped (PRD-first filter): §1.8 `combinatorial_formula/staffing_round_per_component_then_sum` — its pinned literals (staffing 5000 / after-hours 3750 / total 13750 from custodial 3333 x 1.5h actual) ignore the PRD §3.6 minimum-shift floor (0 < 1.5 < 2.0 bills exactly 2.0h), which the PRD uniquely derives as staffing 6666 / after-hours 5000 / total 16666; the instance's 8749-vs-8750 rounding-order discrimination is unreachable under the floor. Gap left as a gap per the Core rule.

Recipe-vs-PRD divergences resolved in favor of the PRD (assertions unchanged, mechanics adjusted):
- `insurance_headcount_tier_100_boundary` and `insurance_window_must_cover_event_end`: the insurance hard gate runs at submission too (§3.3), so coverage was degraded between submit and approve (revoke while SUBMITTED — the §3.3 cascade only touches UNDER_REVIEW) to surface ERR_INSURANCE_INSUFFICIENT at the approval gate as the instances intend.
- `facility_blocked_interval_half_open_adjacency` (reject leg) and `invalid_time_window_variants` (inverted/13h legs) and `reference_invalid_on_stale_policy_and_bad_renewal` (policy leg): §2.9 tiers 6/7/8 apply to request creation, so the pinned errors are asserted at the creation call — the earliest mandated surface.
- `waitlist_promotion_on_permit_cancel`: an overlapping request cannot be created/submitted once a permit blocks the interval (tier 7), so the WAITLISTED state is reached via §3.4 approval-time arbitration (earlier-submitted request wins the P2 tie) instead of the unreachable manual-waitlist path.
- `invoice_accrual_pay_and_damage_shortfall_conservation`: damage intake moved before the FEE_PAYMENT — §3.5 releases the held deposit when a FINAL invoice settles with no OPEN/ADJUDICATED/APPEALED assessment, so the recipe's pay-first order would leave no deposit to forfeit. All pinned literals (62225 / 10000 / 5000 / outstanding 62225 -> 0 -> 5000 -> 0) preserved.
- `appeal_window_elapsed_and_adjudication_cap`: late appeal asserted via validate_error_is_one_of([ERR_APPEAL_WINDOW_ELAPSED, ERR_INVALID_STATE_TRANSITION]) — §2.4 fires "damage appeal windows close" as a clock-advance transition (auto-FINAL), while §3.8 names the appeal-time rejection; both are 409 and a PRD-only reader could ship either.
- `reference_invalid_on_stale_policy_and_bad_renewal` (renewal leg): error_is_one_of([ERR_RENEWAL_NOT_RENEWABLE, ERR_REFERENCE_INVALID]) — §2.9 tier 8 and tier 12 both claim the same-renter check with different error ids (both 422).
- `site_wide_blackout_aggregate_overlap`: financial_status sub-assertion dropped (zero-gross-paid supersession is pinned only to REFUND_PENDING by §3.7 while the §3.7 zero-refund -> SETTLED clause invites a second faithful reading); lifecycle SUPERSEDED + work-order CANCELLED + provisional VOID asserted.
- Absolute version==1 assertions avoided throughout (PRD pins relative increments only, §2.5).

Final coverage: §1.8 = 17/18 instances (each with exactly 2 tests), §1.9 = 51/51 active instances (2 `excluded_because:` stubs correctly untranslated).

## Step 7: Run Tests and Iterate — 2026-08-14T20:40:00.000Z

The 8-round parallel sweep is fully green: 88/88 passed in every round. Exit condition met.

### Summary

- **Iterations run:** 2 (iteration 1: 8 failing tests, identical across all 8 rounds — deterministic, no flakiness; iteration 2: 88/88 × 8 rounds clean).

- **Tests deleted:** none. Every failing test traced to a verbatim PRD rule.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:**
  - `test_24_seasonal_and_insurance_windows.py::test_seasonal_rate_year_straddle_per_occurrence_pricing` — setup fix (STEP 2 / unique-derivability): `season_end` changed from `2027-01-16T00:00:00Z` to `2027-01-17T08:00:00Z` (local midnight after the last Saturday). The original bound only included the Jan 16 occurrence under a UTC-date-component reading, which contradicts §3.9's "in site-local time"; the new bound yields exactly the 4 intended occurrences under instant, site-local-date, and date-component readings alike. The asserted rule (per-occurrence pricing across the rate-year boundary, §3.9/§3.2) is unchanged.
  - `test_07_site_close_cascade.py::_site_with_pending_request` — fixture fix: dropped `insurance=False` so the helper's SUBMITTED request satisfies §3.3's verbatim submission-time insurance hard gate ("a hard gate at submission, resubmission, and approval"), which the implementation was missing and now enforces.

- **Fixes applied to `implementation/`:**
  - `routes/ops.py::create_request` — removed the creation-time capacity gate (§2.9 tier 5 applies only to "submission, resubmission, and approval", so an over-capacity DRAFT must be creatable); added the missing tier-7 permit blocked-interval conflict check ("the requested interval must not collide with ... the blocked interval of an ISSUED or ACTIVE permit ... Applies to request creation and submission"); added the missing tier-8 covering-policy check (`ERR_REFERENCE_INVALID`).
  - `routes/ops.py::_submit_gates` — added the §3.3 insurance hard gate (tier 5) and the tier-7 permit blocked-interval conflict check to submission/resubmission.
  - `routes/ops.py::post_payment` — overpayment check now precedes the invoice state gate: a FEE_PAYMENT against a PAID invoice (remaining balance 0) yields `ERR_OVERPAYMENT` per §3.5's verbatim "may not exceed the target invoice's remaining balance ... or ... ERR_OVERPAYMENT".
  - `validation.py::issue_invoice` + `routes/ops.py::verify_wo` — stamp the renter's arrears clock (`_balance_since`) at the moment `outstanding_balance_cents` first goes above zero, instead of lazily at the next clock sweep; §3.3's "stays above zero continuously for thirty or more days" now measures from the true accrual instant.
  - `validation.py::init_common` / `request_priority_key` — added an internal monotonic creation sequence `_seq` as the final arbitration tiebreaker: `created_at` is taken from the logical clock and ties to the millisecond, which previously left §3.4's approval-time demotion with no winner (id remains unused as an ordering key, per PRD).
  - `routes/ops.py::create_series` — reordered renewal validation: `expected_series_version` presence/type/match (`ERR_INVALID_REQUEST`/`ERR_STALE_VERSION`) is now evaluated before the renewability linkage check, keeping §2.8's canonical stale-version example ("another writer has just renewed the same series") reachable instead of being masked by `ERR_RENEWAL_NOT_RENEWABLE`.
  - `routes/core.py::create_policy` + `util.py` — made the policy-supersession overlap check robust to open-ended (`null` `effective_to`) windows via a `FAR_FUTURE` sentinel, per §3.2's open-ended policy rule (previously a latent `TypeError`→500 path).

## Step 8: Finalize PRD — 2026-08-14T20:50:00.000Z

PRD_FINALIZED.md is complete. Final report:

**Line counts / delta:** PRD.md 349 lines (67,841 bytes) vs PRD_FINALIZED.md 349 lines (69,786 bytes) — 0% line delta (all eight edits are inline revisions to existing sentences; no sections added or removed), +2.87% by bytes (+1,945).

**Changes (one bullet per edit):**

- **§2.9 (tier 7)** — revise — "Applies to request creation and submission" → "Applies to request creation, submission, and resubmission" — `implementation/routes/ops.py:176-184` (`_submit_gates`, shared by `submit_request` at ops.py:196 and `resubmit_request` at ops.py:229, runs all four tier-7 checks at both).
- **§3.2 (coverage sentence)** — revise — appended "an open-ended policy — null `effective_to` — covers every event start at or after its `effective_from`" — `implementation/validation.py:258-269` (`policy_for`: `et is None or starts_at < et`).
- **§3.2 (supersession sentence)** — revise — appended "for this overlap test an open-ended window is unbounded — a null `effective_to` compares as later than any finite instant" — `implementation/routes/core.py:303-314` + `implementation/util.py:18` (`FAR_FUTURE` sentinel).
- **§3.3 (standing paragraph)** — revise — pinned the thirty-day arrears continuity as "measured from the instant the balance first rises above zero, and restarted whenever the balance returns to zero and later rises again" — `implementation/validation.py:417-424` (`issue_invoice` eager `_balance_since` stamp), `implementation/routes/ops.py:704-711` (`verify_wo`), sweep at `implementation/services.py:293-305`.
- **§3.4 (submission gate list)** — revise — inserted "the insurance gate of §3.3 must pass for a non-`INTERNAL` renter (else `ERR_INSURANCE_INSUFFICIENT`)" into the submission gate enumeration, which previously omitted it — `implementation/routes/ops.py:170-172`.
- **§3.4 (priority paragraph)** — revise — after the `created_at` tiebreak, added "requests whose `created_at` stamps coincide … fall back to their creation arrival order"; "The resource `id` is never used as an ordering key" kept verbatim — `implementation/validation.py:18,33-36` (`_seq` in `init_common`), `validation.py:275-286` (`request_priority_key`).
- **§3.5 (fee-payment rule)** — revise — appended "this remaining-balance check is evaluated before the invoice's state gate, so a payment against an invoice whose remaining balance is zero … fails as an overpayment rather than as a state error" — `implementation/routes/ops.py:544-550` (`post_payment` FEE_PAYMENT branch).
- **§3.9 (renewal paragraph)** — revise — appended the fixed renewal validation order (source existence → `expected_series_version` presence/type → version match → remaining renewability conditions) so §2.8's canonical stale-renewal case yields `ERR_STALE_VERSION`, not `ERR_RENEWAL_NOT_RENEWABLE` — `implementation/routes/ops.py:992-1008`.
- **§3.9 (generation sentence)** — revise — pinned season bounds as site-local calendar dates: an occurrence is generated for every matching weekday whose site-local date falls on or between the site-local dates of `season_start`/`season_end` (both inclusive) — `implementation/util.py:140-157` (`expand_occurrences`).

**Step-7 items with no PRD edit (PRD already determines behavior, prose kept verbatim):** the `create_request` capacity-gate removal (§2.9 tier 5's "Applies to submission, resubmission, and approval" already excludes creation), the `create_request` tier-7 permit blocked-interval check (tier 7 already lists request creation), and the `create_request` tier-8 covering-policy check (tier 8 already lists request creation).

**Per-edit pre-edit search log:**

1. **§2.9 tier 7 resubmission.** (a) Subject: tier-7 availability/conflict checks at resubmission. (b) Enumerated: `create_request` (ops.py:83-95), `_submit_gates` (ops.py:162-186) shared by submit/resubmit (ops.py:189-236), `begin_review` (ops.py:251-263 — facility-only, pre-existing narrowing pinned by §3.4), `approve_request_ep` (ops.py:304-314), `expand_series` (services.py:383-391), `create_event` (core.py:556-574), `create_facility` (core.py:135-136). (c) None — the only resubmission path applies all four checks, so the widened applies-to is consistent everywhere.
2. **§3.2 open-ended coverage/supersession.** (a) Subject: null `effective_to` semantics. (b) Enumerated: `policy_for` (validation.py:258-269) and all its callers (ops.py:98, 316, 440, 689; services.py:130, 391); supersession loop (core.py:303-314); `util.FAR_FUTURE` (util.py:18); §2.4's general half-open rule — confirmed only rate policies can be open-ended (cert `effective_to` is required at core.py:447). (c) Scoped both clauses to policies/this overlap test so §2.4 and other interval types are untouched.
3. **§3.3 arrears clock.** (a) Subject: start/reset of the 30-day continuity. (b) Enumerated: eager stamps in `issue_invoice` (validation.py:417-424) and `verify_wo` (ops.py:704-711); sweep suspend/clear/lazy-fallback (services.py:293-305); `recompute_standing` pop-on-restore (validation.py:443-457); balance reductions via `post_payment` (ops.py:553-556) and `void_invoice` (validation.py:434-440). Every 0→positive rise passes through an eager-stamp site. (c) Added "restarted whenever the balance returns to zero and later rises again" to cover the reset paths, not just the initial stamp.
4. **§3.4 submission insurance gate.** (a) Subject: submission gate enumeration. (b) Enumerated: `_submit_gates` (ops.py:162-186, both submit and resubmit), approval gate (ops.py:302-303, already pinned in §3.4's approval paragraph), `expand_series` per-occurrence insurance (services.py:388, pinned by §3.9's "conflict and insurance checks"). (c) Used the approval paragraph's existing phrasing ("The insurance gate of §3.3 must pass for a non-`INTERNAL` renter") to keep the two paragraphs parallel.
5. **§3.4 priority tiebreaker.** (a) Subject: final arbitration tiebreak. (b) Enumerated: `request_priority_key` (validation.py:275-286) and its only callers, `run_waitlist_sweep` (validation.py:484) and approval demotion (services.py:209); `_seq` assignment in `init_common` (validation.py:33-36); list-endpoint `created_at` sorts (ops.py:141, 158, etc.) — those are governed by §2.3, not the §3.4 arbitration paragraph. (c) Clause scoped to same-instant ties among "Candidates" so list sorting is not mis-described; the id-never-used sentence preserved verbatim.
6. **§3.5 overpayment precedence.** (a) Subject: order of remaining-balance check vs invoice-state gate. (b) Enumerated: `post_payment` FEE_PAYMENT branch (ops.py:539-572: reference → overpayment → state); DEPOSIT_CAPTURE branch (ops.py:528-538: state before amount — deliberately untouched); grep confirmed no other `ERR_OVERPAYMENT` site; §2.9 tier list never slots the invoice-state check, so no tier-order claim is contradicted. (c) Wording names `FEE_PAYMENT` and "the invoice's state gate" explicitly, a local ordering statement only.
7. **§3.9 renewal order.** (a) Subject: existence/OCC/renewability check order in renewal creation. (b) Enumerated: `create_series` renewal block (ops.py:992-1008 — exact order pinned); §2.8 renewal bullet (already describes the stale case; my addition makes it reachable); non-renewal creation ignores the field (ops.py:969 read, validated only inside the renewal branch); no other endpoint accepts `expected_series_version` (§2.8). (c) Scoped with "Within renewal creation"; existence check explicitly kept before the OCC checks to match impl.
8. **§3.9 season bounds.** (a) Subject: how `season_start`/`season_end` bound occurrence generation. (b) Enumerated: `expand_occurrences` (util.py:140-157 — local-date iteration, inclusive); span validation in `create_series` (ops.py:978-981 — instant-based, in §3.9's first paragraph, untouched); series completion in `sweep_clock` (services.py:317-321 — instant-based `now > season_end`, untouched). (c) Clause embedded inside the "Generation expands…" sentence and phrased "an occurrence is generated for every matching weekday…" so it cannot be misread as governing span validation or completion.

## Step 9: Complete PRD — 2026-08-14T21:20:00.000Z

All changes verified. The task is complete.

**File produced:** `workspace/PRD_COMPLETED.md`

**Size delta:** PRD_FINALIZED.md 349 lines / 69,786 chars → PRD_COMPLETED.md 349 lines / 79,121 chars. Char delta **+9,335**; line count unchanged (every change is an in-paragraph insert/revision; no new sections).

**Counts:** 34 ambiguity-pins, 10 mismatch-revisions (44 changed paragraphs total, matching the 44 revised lines).

### Mismatch revisions (PRD described behavior impl does not exhibit)
- §2.4 — revise — mismatch — appeal window (14d) and suspension clock (30d) are exact elapsed 24h-day durations from the adjudication/balance-rise instant, not site-local calendar days (only cancellation tiers use calendar days) — `implementation/services.py:301,311`, `implementation/routes/ops.py:917`
- §2.9 tier 2 — revise — mismatch — segregation-of-duties check runs after path/body validation, immediately before the lifecycle-state check, not at the role tier — `implementation/routes/ops.py:876-879, 932-935`
- §2.9 tier 6 — revise — mismatch — future-start rule enforced at submission/resubmission only; past-dated DRAFT creation is allowed — `implementation/routes/ops.py:84, 173-175`
- §2.9 tier 8 — revise — mismatch — for seasonal series the policy-coverage check runs per occurrence during generation, not at series creation — `implementation/routes/ops.py:956-1008`, `implementation/services.py:391`
- §3.1 — revise — mismatch — maintenance hold carries no time window and demotes every request in SUBMITTED/UNDER_REVIEW/REVISION_REQUESTED/RESUBMITTED regardless of window; `hold_reason` is optional — `implementation/routes/core.py:193-211`
- §3.3 — revise — mismatch — suspension blocks submissions only; clock-driven activation of SECURED permits is not interposed — `implementation/services.py:274-291`
- §3.3 — revise — mismatch — no insurance sufficiency pre-validation at certificate upload; gate runs only at submission/resubmission/approval — `implementation/routes/core.py:434-466`
- §3.4 — revise — mismatch — NONPROFIT + `district_sponsored` promotes to P1 automatically at submission, not at director's discretion — `implementation/validation.py:289-295`
- §3.5/§3.8 — revise — mismatch — `DAMAGE_CHARGE` never posts (kinds are five); the shortfall is carried by the DAMAGE invoice alone; system-posted rows carry null `idempotency_key` — `implementation/services.py:236-238`, `implementation/validation.py:368-380`
- §3.6 — revise — mismatch — no VERIFIED → BILLED transition exists; the order remains VERIFIED — `implementation/routes/ops.py:664-712`

### Ambiguity pins (PRD silent; pinned to impl)
- §2.2 — insert — ambiguity — `api_request_timestamp` is taken from the logical clock — `implementation/response.py:22`
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` rejected with ERR_INVALID_REQUEST — `implementation/response.py:50-70`
- §2.3 — insert — ambiguity — `total_count` is the filtered count before pagination; `has_more` = offset + returned < total_count — `implementation/response.py:31-37`
- §2.3 — insert — ambiguity — creation-timestamp ties keep creation arrival order — `implementation/routes/core.py:163` (stable sort pattern in all list handlers)
- §2.3 — insert — ambiguity — `GET /district/sites/{site_id}/facilities` is the one non-paginated list endpoint — `implementation/routes/core.py:155-165`
- §2.3 — insert — ambiguity — per-endpoint filter-parameter mapping for all 20 list endpoints; unlisted params ignored — all list handlers in `implementation/routes/core.py` and `implementation/routes/ops.py`
- §2.4 — insert — ambiguity — time-based transitions fire at reach-or-pass of their instant, except series completion which requires strictly-after `season_end` — `implementation/services.py:256-321`
- §2.5 — insert — ambiguity — `version` starts at 1 at creation — `implementation/validation.py:35`
- §2.6 — insert — ambiguity — child id not owned by its path parent yields ERR_NOT_FOUND — `implementation/routes/ops.py:54-55`
- §2.8 — insert — ambiguity — the approval version match is evaluated after the lifecycle-state check, before safety gates — `implementation/routes/ops.py:289-293`
- §2.9 tier 7 — insert — ambiguity — sub-check selectivity: begin-review checks only facility availability; facility creation only site-active; event creation skips facility availability — `implementation/routes/ops.py:259`, `implementation/routes/core.py:135, 548-574`
- §2.10 — insert — ambiguity — idempotency check runs right after body validation, before state/fiscal gates; identical replay returns the original row with 201 — `implementation/routes/ops.py:517-522`
- §3.1 — insert — ambiguity — site close / facility retire refusal error is ERR_INVALID_STATE_TRANSITION — `implementation/routes/core.py:86, 235`
- §3.1 — insert — ambiguity — facility `capacity` < 1 rejected with ERR_INVALID_REQUEST — `implementation/routes/core.py:126-127`
- §3.1 — insert — ambiguity — event `facility_id` outside the path site rejected with ERR_REFERENCE_INVALID — `implementation/routes/core.py:553-555`
- §3.1 — insert — ambiguity — tier-0 event colliding with an ACTIVE permit (not preemptable) is rejected with ERR_SCHEDULE_CONFLICT — `implementation/routes/core.py:570-574`
- §3.2 — insert — ambiguity — policy field-constraint violations → ERR_INVALID_REQUEST; bad effective window → ERR_INVALID_TIME_WINDOW — `implementation/routes/core.py:271-283`
- §3.3 — insert — ambiguity — certificate limit violations → ERR_INVALID_REQUEST; bad coverage window → ERR_INVALID_TIME_WINDOW — `implementation/routes/core.py:448-454`
- §3.4 — insert — ambiguity — nonexistent `facility_id` at creation → ERR_NOT_FOUND; `headcount_estimate` < 1 → ERR_INVALID_REQUEST — `implementation/routes/ops.py:81, 79-80`
- §3.4 — insert — ambiguity — `request_priority_class` is null until first submission — `implementation/routes/ops.py:109`
- §3.4 — insert — ambiguity — all four resubmission fields optional; empty resubmission still accepted and increments `revision_round` — `implementation/routes/ops.py:209-226`
- §3.4 — insert — ambiguity — approval response `data` is the newly minted Permit, not the request — `implementation/routes/ops.py:322-323`
- §3.4 — insert — ambiguity — request lapse fires when the clock reaches or passes `starts_at` — `implementation/services.py:267-271`
- §3.5 — insert — ambiguity — deposit is computed from the post-rebate `rental_fee_cents` — `implementation/services.py:74-77, 142-143`
- §3.5 — insert — ambiguity — DEPOSIT_CAPTURE against a permit no longer in DEPOSIT_PENDING → ERR_INVALID_STATE_TRANSITION — `implementation/routes/ops.py:529-532`
- §3.5 — insert — ambiguity — a lapsed permit lands financial SETTLED with no refund/forfeiture transactions — `implementation/services.py:287-291`
- §3.5 — insert — ambiguity — FEE_PAYMENT `invoice_id` must reference an invoice of the path permit (else ERR_REFERENCE_INVALID); cancellation-waterfall refund rows carry the REFUND invoice id, settlement/finalization DEPOSIT_REFUND rows carry null — `implementation/routes/ops.py:540-543`, `implementation/validation.py:543-549`
- §3.6 — insert — ambiguity — completion allowed once the clock reaches or passes `occupancy_end`; earlier attempts → ERR_INVALID_STATE_TRANSITION — `implementation/routes/ops.py:433-435`
- §3.6 — insert — ambiguity — completion requires a covering ACTIVE policy, else ERR_REFERENCE_INVALID — `implementation/routes/ops.py:440-443`
- §3.6 — insert — ambiguity — the FINAL invoice at completion bills the estimated span; verification later recomputes from actuals — `implementation/routes/ops.py:455-458`
- §3.6 — insert — ambiguity — verification recomputes the FINAL only while still ISSUED (PAID left untouched), shifting outstanding by the total delta, using the ACTIVE policy at occupancy start if one exists — `implementation/routes/ops.py:685-711`
- §3.6 — insert — ambiguity — `estimated_hours` rounds half-up to two decimals; `actual_hours` rounded to two decimals at attestation, missing/non-positive → ERR_INVALID_REQUEST — `implementation/util.py:79-81`, `implementation/routes/ops.py:669-680`
- §3.6 — insert — ambiguity — a fractional rental product (odd half-hour blocks at an odd rate) is truncated toward zero to integer cents — `implementation/services.py:33-39`
- §3.6 — insert — ambiguity — each FEE_PAYMENT against a FINAL/DAMAGE invoice subtracts its own amount from outstanding as it posts — `implementation/routes/ops.py:553-556`
- §3.7 — insert — ambiguity — `refund_destination` must be CREDIT or CARD when supplied, else ERR_INVALID_REQUEST — `implementation/routes/ops.py:417-419`
- §3.7 — insert — ambiguity — the REFUND invoice is issued for the net payout (post-fee), only when above zero — `implementation/validation.py:537-539`
- §3.8 — insert — ambiguity — negative adjudicated/final amounts → ERR_INVALID_REQUEST — `implementation/routes/ops.py:874-875, 930-931`
- §3.9 — insert — ambiguity — a RenterOrgRep must supply their own org id as body `renter_org_id`, else ERR_FORBIDDEN_FOR_ROLE — `implementation/routes/ops.py:970-971`
- §3.9 — insert — ambiguity — exact recurrence grammar `WEEKLY:DAY:HH:MM-HH:MM` (end strictly after start); malformed → ERR_INVALID_REQUEST — `implementation/util.py:117-137`, `implementation/routes/ops.py:975-977`
- §3.9 — insert — ambiguity — occurrence requests take `series_name` as title, `headcount_estimate` 1, `district_sponsored` false, creation instant as `submitted_at` — `implementation/services.py:361-376`
- §3.9 — insert — ambiguity — occurrence approval runs the full gate set; failed occurrences persist as DENIED with `denial_reason_code` CALENDAR_CONFLICT — `implementation/services.py:383-398`
- §3.9 — insert — ambiguity — zero approved occurrences leaves the series in PENDING_GENERATION — `implementation/routes/ops.py:1026-1030`

## Final Verification Sweep — 2026-08-14T21:35:00.000Z

Orchestrator-rerun 8-round parallel sweep (`prd-bench-local-run --isolation per-test-server`) after Steps 8-9 to materialize the canonical `results.{1..8}.json` artifacts and independently confirm the Step 7 green claim: all 8 rounds 88/88 passed. Results files persisted at `workspace/implementation/results.{1..8}.json`.
