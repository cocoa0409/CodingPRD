# Worklog — task_1233_life_insurance_policy_administration

## Step 1: Create task directory — 2026-08-12T03:50:44.207Z

Task directory pre-assigned: `tasks/task_1233_life_insurance_policy_administration/` with `workspace/` subdirectory. Directory verified to exist; Step 1 treated as done per orchestration instructions (no auto-index scan run).

## Step 2: Generate scaffold — 2026-08-12T04:07:01.583Z

All three files generated and lint passes clean.

## Summary

Generated scaffold artifacts for **task_1233_life_insurance_policy_administration** at `/home/ubuntu/github/CodingPRD/tasks/task_1233_life_insurance_policy_administration/`:

**Files** (3,545 total lines):
- `SCAFFOLD.yaml` (1,660 lines)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1,110 lines)
- `SCAFFOLD_CORNER_DESIGN.yaml` (775 lines)

**Counts**:
- **Entities**: 13 — InsuredPerson, ProductTemplate, PolicyApplication, Policy (with parallel `premium_payment_status` × `form_status` dimensions), PremiumBillingCycle, PolicyLoan, LoanInterestAccrual (append-only), DividendDeclaration, NonforfeitureElection, ReinstatementRequest, Rider, ConversionRequest, CashValueLedgerEntry (append-only)
- **State machines**: 8 — including PolicyApplication cycle (UNDER_REVIEW↔EVIDENCE_REQUIRED), Policy parallel dimensions, ReinstatementRequest cycle, terminal-state lockdowns
- **Calculations**: 10 — modal_premium_at_issue (nested rounding), monthly_coi_charge (dual variant: end_of_month vs beginning_of_month), policy_loan_interest_accrual (capitalizing vs non_capitalizing), reduced_paid_up_face_amount (age-tiered), extended_term_duration, cash_surrender_value (waterfall), back_premium_due (chronological + interest), grace_period_expiry_check (boundary), dividend_payout (weighted scoring by option), paid_to_date_advance
- **Validations**: 13 priority-ordered — auth → authorization → existence → state → segregation_of_duties → temporal windows → referential → constraints → class-tobacco consistency → fiscal (loans/nonforfeiture/reinstatement) → OCC
- **Endpoints**: 66 — includes `POST /_clock/set_current_utc` (default 2026-05-01T00:00:00Z), full CRUD + actions, plus flat filtered-list GETs (`/policy-loans`, `/premium-billing-cycles`, etc.) for FK reverse-reachability
- **Errors**: 22 — including domain-specific `ERR_SEGREGATION_OF_DUTIES_VIOLATION`, `ERR_WINDOW_EXPIRED`, `ERR_CLASS_TOBACCO_MISMATCH`, `ERR_INSUFFICIENT_CASH_VALUE`, `ERR_STALE_VERSION`, `ERR_PRODUCT_NOT_PARTICIPATING`, `ERR_ALREADY_TERMINAL`
- **Roles**: 5 — PlatformAdmin (opaque), Agent (entity_backed:InsuredPerson), Underwriter (opaque), PolicyIssuer (opaque), Policyholder (entity_backed:InsuredPerson); role_model = segregation_of_duties
- **Concurrency rules**: 2 — OCC on Policy.version for mode-change and dividend-option

**Difficulty design**: 9 rules × 2 instances = 18 difficulty instances, covering dual-variant calcs (loan interest capitalizing vs not; CoI deduction timing), combinatorial formulas (nested rounding; multi-input tiered), non-linear state machines (Policy parallel dims; ReinstatementRequest cycle), transitive cascades (clock→cycle→policy→loan/rider depth-3; nonforfeiture depth-2), priority conflicts (state vs business_safety; referential vs fiscal), boundary precision (grace-period date boundary; loan-availability cents boundary), cross-entity state deps (Application↔Cycle; Rider↔Policy), temporal overlap (reinstatement half-open window; conversion closed-inclusive), compensating invariants (cash_value+outstanding_loan conserved; dividend_accumulation+face conserved).

**Corner design**: 9 sections, 21 active instances + 3 excluded stubs (with §1.8 back-references), covering entities/state-machines/calculations/validations/endpoints/errors/RBAC/OCC/immediate-consistency.

**Lint verdict**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (66 endpoints, 13 entities, 18 §1.8 + 21 §1.9 instances, 315 calls scanned, 0 violations).

## Step 3: Copy shared files — 2026-08-12T04:07:24.797Z

Copied `./INSTRUCTION.md` → `tasks/task_1233_life_insurance_policy_administration/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-12T04:20:18.215Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1233_life_insurance_policy_administration/workspace/PRD.md` (~460 lines). The withheld difficulty/corner design files were never opened.

**Document structure** (skeleton designed from the domain, not copied from the example):
- §1 Introduction — two paragraphs from carrier-operations and auditability/deterministic-time angles
- §2 Global Specifications — 12 subsections: RBAC (with per-role `identity` prose: `Agent`/`Policyholder` entity-backed by `InsuredPerson`, `PlatformAdmin`/`Underwriter`/`PolicyIssuer` opaque), verbatim §2.2 envelope block, pagination (limit 10/1/100, offset 0, `created_at` ascending), the logical clock (startup default `2026-05-01T00:00:00Z`, clock-advance auto-transitions), common resource properties (including the explicit `updated_at`/`version` absence for `LoanInterestAccrual` and `CashValueLedgerEntry`), integer-cents/round-half-up precision with pinned rounding stages, the cash value ledger (8 entry types, chronological ordering with the forbidden `id` tiebreak), dual policy state dimensions, left-to-right nested 404 validation, OCC (both rules: `expected_policy_version` → `ERR_STALE_VERSION` 412), segregation of duties (three two-person chains), and the full 13-level validation priority order in prose
- §3 Business Logic — 11 subsections organized by lifecycle: insureds/products → application/underwriting → issuance/modal premium → billing/grace/lapse → cash value/COI → loans → dividends → non-forfeiture → reinstatement → riders/conversion → read model. All 10 calculations rendered as precise prose (pinned rounding order for modal premium, anniversary-split 365-day loan accrual with both capitalizing variants, age-banded RPU/ET rate schedules with substandard loadings, surrender waterfall, 6% back-premium interest, strict `>` grace boundary, oldest-first payment allocation)
- §4 Endpoint table — 66 rows, 4 columns only, matching the scaffold exactly
- §5 Error catalogue — 22 rows, 2 columns only, matching the scaffold exactly

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 99 required occurrences (90 unique identifiers incl. endpoint inputs/path params), 90 present, 0 missing
- endpoints[].request_body: 39 required, 39 present, 0 missing
- endpoints[].query_params: 12 required, 12 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 13 checked, 13 expressed in prose (§2.12 ordered narrative), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint + expected_policy_version + ERR_STALE_VERSION/412 named), 0 missing
- state_machines[].transitions: 30 checked, 30 fully expressed (from/to states, preconditions with error IDs, side effects), 0 missing
- calculations[]: 10 checked, 10 fully expressed in precise prose (no pseudocode, no fuzzy words), 0 missing
- validations[] conditions: 13 checked, 13 matchable to error_id in prose (all 22 error IDs appear before §5), 0 missing
- endpoints[].side_effects / applies_to: all expressed (a gap for mode-change's recompute side effect was found and repaired during verification), 0 missing
- entities[].fields[] structured content: defaults/enums/formats reconstructible (dividend_option default CASH, 500 bps loan rate, 31-day grace, 5-year windows, 8-digit policy_number, etc.), 0 missing
- sibling-branch symmetry: 4 groups checked (3 election types, 4 dividend options, 2 rider exercises, approve/decline pairs), equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 430
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All three contracts PASS. §2.2 was emitted verbatim from `section-2.2-response-structure.md`, and no pseudocode operators or approximating language appear anywhere in the document.

## 2026-08-12 — Unit test generation (prd-bench-unit-test-generator)

Stage 1 (test_helpers/): types, api_client (66 endpoint methods), api_errors (22 errors registered), assertions, factories, constants, test_users (entity-backed Agent/Policyholder per-instance builders), fixtures (issued/funded/loaned/lapsed/reinstated policy composites). Import smoke: PASS.

Stage 2 (test_suite/): 55 tests in 7 files, all collected by pytest.
- Queue A (Difficulty): 32 tests over 16 of 18 instances (>=2 each).
- Queue B (Corner): 23 tests over all 21 non-stub instances (>=1 each); 3 excluded_because stubs not translated (cross-references verified to resolve).
- Skipped (PRD-first filter): Difficulty/cross_entity_state_dependency/issue_requires_first_cycle_paid (PRD §3.3 establishes the first cycle and posts the initial PREMIUM_CREDIT at issuance, so rejection of issue-after-approve is not uniquely derivable; contradicted by every other audited recipe) and Difficulty/priority_pair_validation_conflict/fiscal_vs_business_referential_loan (PRD names no loan-origination state gate; post-election cash value unspecified — asserted error not uniquely derivable).
- Recipe literal corrections (PRD is the contract; design-YAML arithmetic recomputed): loan accrual 250685 (not 250068), modal premium QUARTERLY 438 / ANNUAL 1716 (not 13090), CoI debit -50 pre-credit vs -40 post-credit (not -2000), RPU age-40 face 50007200 / age-39 66676267 (response-driven cash), grace/reinstatement/conversion window dates made response-driven to stay valid under any PRD-faithful cycle-creation model; window semantics follow PRD "must not be later than" (inclusive) with ±30-day margins for 365-day-year ambiguity.

Audit: every test docstring carries verbatim PRD citations (literal whitespace-normalized grep of workspace/PRD.md: 0 failures) and ends with exactly one resolving Design: line. No skip/xfail markers. No scaffold references in generated code.

## Step 5: Generate unit tests — 2026-08-12T04:56:12.669Z

Generation complete. Summary:

## Deliverables

**Stage 1 — `test_helpers/`** (9 files): `types.py` (all 13 entities; append-only `LoanInterestAccrual`/`CashValueLedgerEntry` correctly omit `updated_at`/`version`), `api_client.py` (66 endpoint methods covering every PRD §4 row), `api_errors.py` (all 22 error IDs registered with the framework status map), `assertions.py`, `factories.py`, `constants.py` (class multipliers, mode factors, 500 bps / 365-day, 31-day grace, age-banded RPU/extended-term rates), `test_users.py` (opaque shared constants + mandatory `make_agent_headers`/`make_policyholder_headers` per-instance builders for the entity-backed roles), `fixtures.py` (issued-policy composite, cash funding via premium payments, loan origination, lapse, full reinstatement flow), `__init__.py` barrel. Import smoke: PASS.

**Stage 2 — `test_suite/`** (conftest + 7 test files): **55 tests, all collected by pytest.**

- **Queue A (Difficulty): 32 tests over 16 of 18 instances** (≥2 per instance).
- **Queue B (Corner): 23 tests over all 21 non-stub instances** (≥1 each). The 3 `excluded_because:` stubs were not translated; all three cross-references verified to resolve to real difficulty instances.

## Skipped instances (PRD-first filter)

1. `Difficulty/cross_entity_state_dependency/issue_requires_first_cycle_paid` — its expectation (issue-after-approve rejected with ERR_INVALID_STATE) contradicts PRD §3.3, which establishes the first cycle and posts the initial `PREMIUM_CREDIT` at issuance, and contradicts every other audited recipe (including corner instance `policy_initial_state_is_current_in_force`, which issues after the identical call sequence and expects success). Not uniquely derivable → gap left as gap.
2. `Difficulty/priority_pair_validation_conflict/fiscal_vs_business_referential_loan` — PRD names no state gate for loan origination (`ERR_INCOMPATIBLE_REFERENCE` is scoped to conversion/rider creation only) and does not specify cash value after a reduced paid-up election; three error outcomes are all PRD-plausible.

## Recipe-literal corrections (PRD is the contract)

Several pre-computed YAML expected values were arithmetically wrong against the PRD's own pinned formulas; tests assert the PRD-derived values instead: loan accrual 250685 (not 250068), modal premium 438/1716 for QUARTERLY/ANNUAL (not the self-contradictory 13090), CoI debit −50 pre-credit vs −40 post-credit (not −2000), RPU face 50007200 at age 40 / 66676267 at age 39. Grace/lapse and 5-year window tests are response-driven (read `grace_period_end_date`/`paid_to_date`/`issue_date` from the API) so they hold under any PRD-faithful billing-cycle creation model; window assertions follow the PRD's inclusive "must not be later than" semantics with ±30-day margins (365-day-year vs calendar-year ambiguity).

## Stage-gate verdicts

- **C1/C2/C3**: every docstring citation survives a literal whitespace-normalized grep of `PRD.md` (0 failures over 55 tests; all quotes restored to raw PRD text including markdown emphasis).
- **C4**: every test docstring ends with exactly one `Design:` line resolving to a real instance; no stub tags, no untagged or dual-tagged tests.
- **Coverage**: Queue A ≥2/instance and Queue B ≥1/non-stub-instance satisfied everywhere except the two sanctioned skips.
- **No** `skip`/`skipif`/`xfail` markers; no scaffold references in generated code.

## Step 6: Generate implementation — 2026-08-12T04:56:12.669Z

All 66 spec endpoints are registered (the 67th is Flask's built-in static route). The implementation is complete and verified.

## Summary

**Generated** a complete Python + Flask implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1233_life_insurance_policy_administration/workspace/implementation/`:

**Files**
- `start.sh` — executable launcher: guarded `pip install` (no-op once Flask is importable, so per-test reboots are fast), `exec python3 app.py` in the foreground
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — entry point, blueprint registration, error handlers (binds `0.0.0.0`, reads `PORT`, default 10000)
- `db.py` — in-memory store + logical clock (starts at `2026-05-01T00:00:00Z`, **no seeding of any kind** — store starts empty on every boot)
- `errors.py` — full error catalog with exact error IDs and HTTP statuses from SCAFFOLD §1.6
- `response.py` — exact response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; `limit`/`offset`/`total_count`/`has_more` in meta for lists)
- `middleware.py` — auth (`X-User-ID`/`X-User-Role`, five roles), RBAC, pagination validation (limit 1–100, default 10), body parsing
- `domain.py` — enums, constants, record factories, serializers (exactly the declared fields; internal fields `_`-prefixed and never serialized)
- `services/calculations.py` — modal premium (pinned double-rounding: monthly rate rounded half-up *before* mode-factor multiplication), UL monthly COI (net amount at risk, tiered age lookup, pre-credit basis), chronological loan-interest accrual (365-day year, anniversary splitting, capitalizing/non-capitalizing variants), reduced paid-up face, extended-term duration (floor, 60-month cap), surrender waterfall, back-premium-due with 6% reinstatement interest
- `services/engine.py` — append-only cash-value ledger (8 entry types, creation-order tie-break), lazy billing-cycle generation, clock-advance auto-transitions (interleaved per-policy chronological walk: oldest past-due cycle → GRACE → strict `>` lapse at `grace_period_end_date + 1 day` → cascades → auto EXTENDED_TERM election), payment allocation (oldest unpaid first, remainder spawns new cycles), shared non-forfeiture cascade
- `routes/` — 9 blueprints: `core` (clock, insured persons, templates), `applications` (full underwriting workflow + issue with SoD), `policies` (mode-change/dividend-option with OCC on `version` → `ERR_STALE_VERSION` 412), `loans`, `dividends_elections`, `reinstatements`, `riders`, `conversions`, `listings` (flat FK-filtered reads)

**Endpoints: 66** — every route in the PRD §4 table.

**Key design decisions traced to PRD prose**
- Dual state dimensions (`premium_payment_status` × `form_status`) tracked independently; terminal states → `ERR_ALREADY_TERMINAL` vs non-terminal conflicts → `ERR_INVALID_STATE`
- Validation priority order (auth → role → left-to-right path existence → state → segregation-of-duties → windows → referential → field constraints → class/tobacco → fiscal → OCC) enforced as written
- All monetary math via `Decimal` with `ROUND_HALF_UP`; 365-day year; age = floor(days/365)
- TERM_CONVERTIBLE policies post `PREMIUM_CREDIT` ledger entries without building cash value (keeps reinstatement reachable and matches "products that build loanable cash value")
- Policyholder ownership checks compare `insured_person_id` to `X-User-ID` on loan/election/dividend-option writes

**Verification**: ~90 end-to-end assertions across 7 smoke suites all pass (envelope shape, auth/RBAC, underwriting flow, class-tobacco mismatch, issue + SoD 403, modal-premium arithmetic incl. substandard 2500 bps = 4320 annual, OCC 412, dividends by option, loan accrual both variants with exact cents, grace/lapse boundary dates, auto extended-term election, reinstatement with back-premium interest + rider reinstatement, conversion with new policy issuance, non-forfeiture cascades, UL COI ledger ordering, pagination bounds). Two genuine bugs were found and fixed during testing (bulk cycle-gracing overwriting `grace_period_end_date`; partially-paid grace cycles not lapsing). `bash start.sh` boots cleanly on a custom `PORT` and serves within seconds from a fresh process.

## Step 7: Run tests and iterate — 2026-08-12T05:18:06.282Z

All 8 rounds pass 55/55. The transient connection-reset/restart failures from the prior iteration were harness-level load artifacts and did not recur.

## Summary

**Iterations run:** 4 eight-round sweeps (baseline 5/55 → 32/55 → 54/55 → clean 55/55 × 8).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
- `constants.py` (`TEST_DEFAULTS["DATE_OF_BIRTH"]`) and `fixtures.py` (`create_issued_policy` default) — changed `date_of_birth` from `"1990-01-01T00:00:00Z"` to `"1990-01-01"`; PRD §3.1 requires `date_of_birth` "as an ISO calendar date", so the implementation's format check was faithful and the fixture was the bug. Same datetime→date correction applied to every `date_of_birth` literal across `test_02`–`test_07` via targeted sed.

**Fixes applied to `test_suite/`:**
- `test_01_underwriting_and_issuance.py` (`_submitted_application`): default DOB was a datetime split across two lines; changed to `"1990-01-01"`.
- `test_04_calculations.py` (`test_attained_age_39_uses_030_rate`): DOB `1986-05-02` → `1986-05-12`. The old DOB yields 14609 days at the 2026-05-01 election, and floor(14609/365) = 40 under the PRD §2.6 formula the test itself cites — so the test's "age 39" claim was arithmetically inconsistent with PRD; the new DOB yields 14599 days → age 39 → the 0.30 band, keeping the expected value 66,676,267.
- `test_04_calculations.py` (`test_no_charge_when_net_amount_at_risk_not_positive`): now pre-funds the UL policy (`cash_to_add=20_000_000`) so pre-credit cash exceeds face before measuring. PRD §3.5 pins the default COI basis as cash value *before* the current cycle's premium credit; the original test measured a payment whose pre-credit cash was ~100 cents (net at risk positive → a charge correctly fires), contradicting the PRD and its own sibling test.

**Fixes applied to `implementation/`:**
- `services/engine.py` (`record_premium_payment`): removed the unbounded "remainder flows into newly created future cycles" loop. With typical fixture overpayments ($100k against a $5.76 modal premium) it created 17k–200k cycles, causing datetime year-10000 overflows, O(n²) 30s timeouts, and — because all those cycles stood PAID — masking grace/lapse in funded policies. PRD §3.4 describes allocation walking existing cycles in ascending `cycle_index` order; cycles come into existence via clock progression, and the full payment still posts as `PREMIUM_CREDIT` per the verbatim PRD sentence.
- `domain.py`: `APP_TERMINAL = {"DECLINED"}` (removed `"ISSUED"`). PRD §3.2 names only `DECLINED` as "the terminal `DECLINED` state" for applications, so operations on an `ISSUED` application must surface `ERR_INVALID_STATE`, not `ERR_ALREADY_TERMINAL`.
- `routes/reinstatements.py` (`create_reinstatement`): five-year window now measured from `policy["paid_to_date"]` instead of the internal clock-date-at-lapse; PRD §3.9 states verbatim "The lapse date is the policy's `paid_to_date` — the last date through which premiums were fully paid."

## Step 8: Finalize PRD — 2026-08-12T05:21:34.431Z

Both edits are in place, line count unchanged (306 lines, 0% delta). Final summary:

## Summary

**PRD.md vs PRD_FINALIZED.md:** 306 lines → 306 lines, 0% line-count delta; 2 lines modified in place.

**Changes (2 edits):**

- **§3.2 — revise — appended "`DECLINED` is the application's only terminal state: `ISSUED` is not terminal, so an operation attempted against an application in `ISSUED` (or any other state that does not permit the operation) is rejected with `ERR_INVALID_STATE`, never `ERR_ALREADY_TERMINAL`."** — `implementation/domain.py:57` (`APP_TERMINAL = {"DECLINED"}`); `implementation/routes/applications.py:83-92, 120-123, 152-155`.
- **§3.4 — revise — allocation sentence rewritten to pin that payment allocation walks only existing cycles, recording a payment never creates billing cycles (cycles beyond the first arise only via clock progression §2.4), and any unallocated remainder still posts in full as a single `PREMIUM_CREDIT`; UL COI trigger sentence preserved verbatim.** — `implementation/services/engine.py:225-291` (`record_premium_payment`, post-Step-7), `implementation/services/engine.py:131-180` (`run_clock_transitions`).

**Step 7 items judged NOT to need PRD edits** (PRD already pinned the behavior; fixes were to fixtures/tests/impl):
- test_helpers `date_of_birth` datetime→date and test_01 DOB — PRD §3.1 already requires "an ISO calendar date".
- test_04 attained-age DOB `1986-05-02`→`1986-05-12` — test arithmetic was inconsistent with the PRD §2.6 formula it cites; formula unchanged.
- test_04 UL pre-funding — PRD §3.5 already pins the default COI basis as cash value *before* the current cycle's premium credit (verbatim sentence).
- reinstatements five-year window from `paid_to_date` — PRD §3.9 already states verbatim "The lapse date is the policy's `paid_to_date` — the last date through which premiums were fully paid"; the impl was fixed to match.

**Per-edit pre-edit search log:**

*Edit 1 (§3.2 application terminal states):*
- (a) Subject: which application states are terminal; which error (`ERR_ALREADY_TERMINAL` vs `ERR_INVALID_STATE`) surfaces when operating on an `ISSUED` application.
- (b) Paths enumerated and read: `applications.py` in full — `_transition` (lines 83-92, shared by begin-review/request-evidence/submit-evidence/decline), `approve` (116-138), `issue` (148-210); `domain.py:57` (`APP_TERMINAL`). All six application-mutating endpoints check `APP_TERMINAL` first, so with `ISSUED` excluded every one of them surfaces `ERR_INVALID_STATE` on an `ISSUED` application. Also checked PRD §2.8 (terminal form states are policy-scoped — unaffected) and §3.3 ("status advances to `ISSUED`" — consistent).
- (c) Wording adjustment: scoped the claim to *applications* explicitly ("the application's only terminal state") rather than making any universal claim about terminal states, to avoid colliding with §2.8's policy-form terminal set; phrased the ISSUED case as "(or any other state that does not permit the operation)" so it also covers e.g. approve-on-SUBMITTED, which the same code path rejects with `ERR_INVALID_STATE`.

*Edit 2 (§3.4 premium allocation):*
- (a) Subject: whether recording a premium payment can create new billing cycles, and what happens to payment remainder beyond existing unpaid cycles.
- (b) Paths enumerated and read: `engine.py:225-291` (`record_premium_payment` — the Step 7 site), all `create_cycle` callers (`applications.py:197` issuance cycle 1, `conversions.py:144` conversion new-policy cycle 1, `engine.py:94` dead `ensure_cycles`, `engine.py:164` clock-transition loop), the sole payment route `policies.py:137-144`, plus adjacent mutation paths `policies.py:63-101` (mode_change — mutates existing cycles only) and `dividends_elections.py:50-69` (PREMIUM_REDUCTION — mutates existing cycles only). Confirmed cycles are created only at issuance, conversion, and clock advance.
- (c) Wording adjustment: (1) said "cycles beyond the first come into existence only through clock progression (§2.4)" — scoped with "beyond the first" so the issuance/conversion cycle-1 creations are not contradicted; (2) kept the remainder behavior deliberately minimal ("not allocated to any cycle, but the full `amount_cents` still posts as a single `PREMIUM_CREDIT`") — matching the impl, which simply posts the full amount without describing any further disposition; (3) preserved the UL COI-trigger clause and the grace-lifting sentence verbatim so the `record_premium_payment` grace path (`engine.py:263-264`) and COI path (`engine.py:288-289`) remain described.

## Step 9: Complete PRD — 2026-08-12T05:34:18.668Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1233_life_insurance_policy_administration/workspace/PRD_COMPLETED.md` produced.

**Size delta:** source `PRD_FINALIZED.md` 306 lines / 56,934 chars → `PRD_COMPLETED.md` 307 lines / 63,394 chars (+1 line, +6,460 chars). All changes are inline inserts/revisions; no new sections; one new table row in §5.

**Counts:** 30 ambiguity-pins, 8 mismatch-revisions (38 changes total).

**Change log** (section — insert|revise — ambiguity|mismatch — what — impl ref):

- §2.1 — insert — ambiguity — failed Policyholder ownership check surfaces `ERR_INSUFFICIENT_PERMISSIONS` (403) — routes/policies.py:26-30
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST`; per-policy billing-cycle list orders by `cycle_index` ascending — middleware.py:40-63, routes/policies.py:126-134
- §2.4 — insert — ambiguity — `to_iso8601` accepts bare date (midnight UTC) or offset; any instant accepted, no monotonicity requirement — routes/core.py:28-40, util.py:48-69
- §2.9 — insert — ambiguity — generic `ERR_NOT_FOUND` (404) for flat lookups of accruals, ledger entries, dividend declarations, elections, and unmatched routes/methods — app.py:36-42, routes/listings.py:51, routes/loans.py:183, routes/dividends_elections.py:177,197
- §2.12 — insert — mismatch — premium-payments validates `amount_cents` before state checks; accrue-interest parses `as_of_date` before the terminal check — routes/policies.py:137-144, routes/loans.py:80-101
- §3.1 — insert — ambiguity — malformed insured-person fields → `ERR_INVALID_REQUEST` — routes/core.py:46-68
- §3.1 — insert — ambiguity — duplicate `product_code` → `ERR_INVALID_REQUEST`; min ≤ max face; rate tables default to `[]`; `allows_policy_loans` is descriptive, does not gate origination — routes/core.py:106-154
- §3.2 — insert — ambiguity — non-existent body references → `ERR_INSURED_NOT_FOUND` / `ERR_TEMPLATE_NOT_FOUND` — routes/applications.py:29-39
- §3.3 — revise — mismatch — removed the "first cycle PAID/WAIVED + template valid" issuance preconditions; issuance requires only APPROVED + segregation, first cycle is born PAID in the same act — routes/applications.py:148-210
- §3.3 — insert — ambiguity — on TERM_CONVERTIBLE the initial (and every) PREMIUM_CREDIT posts with zero cash-value movement — services/engine.py:20-35, routes/applications.py:204-206
- §3.4 — insert — ambiguity — premium payment: positive-integer amount; requires IN_FORCE form (`ERR_ALREADY_TERMINAL` if terminal) and CURRENT/GRACE billing (`ERR_INVALID_STATE`) — services/engine.py:225-232
- §3.4 — insert — ambiguity — partial payment on a GRACE cycle → cycle PARTIALLY_PAID, policy stays GRACE — services/engine.py:251-268
- §3.4 — revise — ambiguity — mode change rewrites `due_amount_cents` of existing OPEN/PARTIALLY_PAID cycles (auto-PAID if covered); GRACE cycles keep their due — routes/policies.py:89-99
- §3.5 — revise — mismatch — cash value is a running ledger balance on all non-term products (not "scheduled value plus dividends" for whole life); term builds none — domain.py:331-334, services/engine.py:285-287
- §3.5 — insert — ambiguity — COI rate lookup: attained age below every key → lowest entry — services/calculations.py:24-33
- §3.5 — revise — mismatch — deleted the `front_loaded_coi` flag clause (impl never reads it); charge always computed on pre-credit cash value — services/engine.py:239-246
- §3.6 — insert — ambiguity — loan origination requires IN_FORCE form and CURRENT/GRACE billing — routes/loans.py:28-33
- §3.6 — revise — mismatch — accrual fires on repayment, lapse, election, and the admin endpoint only; clock advance does not accrue; endpoint semantics (default date, terminal → `ERR_ALREADY_TERMINAL`, non-after-`last_accrual_date` no-op) — services/calculations.py:50-89, routes/loans.py:80-101, services/engine.py:131-181
- §3.6 — revise — mismatch — policy aggregates decremented by applied amounts on every repayment, not only at REPAID — routes/loans.py:119-131
- §3.6 — insert — ambiguity — repayment overpayment still posts the full amount as LOAN_REPAYMENT_CREDIT and credits cash value in full — routes/loans.py:132
- §3.7 — insert — ambiguity — dividend-option change allowed on any non-terminal-form policy, participating or not — routes/policies.py:104-123
- §3.7 — insert — ambiguity — `policy_year` mismatch → `ERR_INVALID_REQUEST`; declaration applies only when billing is not LAPSED, else immediately FORFEITED — routes/dividends_elections.py:30-46, 93-96
- §3.7 — insert — ambiguity — PREMIUM_REDUCTION with no OPEN cycle applies nothing, no ledger entry — routes/dividends_elections.py:50-69
- §3.7 — insert — ambiguity — PAID_UP_ADDITIONS: age banded at the declaration date; no ledger entry; cash value unmoved — routes/dividends_elections.py:74-89
- §3.8 — insert — ambiguity — election creation requires IN_FORCE form (terminal → `ERR_ALREADY_TERMINAL`, other → `ERR_INVALID_STATE`) and policyholder ownership — routes/dividends_elections.py:112-120
- §3.8 — revise — mismatch — RPU bar is "no prior election of any type", rejected with `ERR_INVALID_STATE` (not just "previously approved") — routes/dividends_elections.py:127-135
- §3.8 — revise — ambiguity — `effective_date`: lapse date when LAPSED, else current clock date — services/engine.py:302-312
- §3.8 — insert — ambiguity — automatic lapse election silently skipped when net available covers less than one month — services/engine.py:215-219
- §3.9 — insert — ambiguity — pre-existing open reinstatement request → `ERR_INVALID_STATE` — routes/reinstatements.py:42-46
- §3.9 — insert — ambiguity — declining a request returns the policy from REINSTATED_PENDING to LAPSED — routes/reinstatements.py:180-184
- §3.10 — insert — ambiguity — rider premium schedule pinned: GI = 0; WOP = 5% of (modal premium // mode months), half-up; face-carrying riders = 0.1% of rider face/month, half-up — services/calculations.py:175-185
- §3.10 — insert — ambiguity — termination refund pro-rated over the current calendar month; negative `amount_cents` accompanies a cash-value increase on value-building products; no entry at zero refund; cascade terminations refund nothing — routes/riders.py:68-101, services/engine.py:201-205,362-365, routes/conversions.py:152-156
- §3.10 — insert — ambiguity — exercise gate failures are `ERR_INVALID_STATE` (WOP needs CURRENT; GI needs policy_year ≥ 3) — routes/riders.py:114-128
- §3.10 — insert — ambiguity — conversion filing requires only a non-terminal source form and a positive-integer face; the source-face cap is enforced at approval — routes/conversions.py:39-57
- §3.10 — insert — ambiguity — approval-time face cap → `ERR_INVALID_REQUEST`; conversion-issued policy inherits application/insured/premium_mode, modal premium from target base rate + inherited class, issue/paid_to_date = conversion date, first cycle OPEN and unpaid with no initial PREMIUM_CREDIT — routes/conversions.py:108-144
- §3.11 — revise — mismatch — "all reads available to every role" narrowed: application list/detail exclude Policyholder — routes/applications.py:14
- §5 — insert — ambiguity — added `ERR_NOT_FOUND` (404) catalogue row — errors.py:35

Notable implementation behaviors now pinned that the PRD previously got wrong: the issuance "preconditions" paragraph (impl has no pre-paid-first-cycle gate), the `front_loaded_coi` flag (absent from impl), anniversary-driven loan accrual (impl never accrues on clock advance), and whole-life cash value as a running premium-fed ledger balance.
