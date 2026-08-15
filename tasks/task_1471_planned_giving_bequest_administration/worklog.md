# Worklog — task_1471_planned_giving_bequest_administration

## Step 1: Create Task Directory — 2026-08-13T10:28:00.000Z

Pre-assigned directory `tasks/task_1471_planned_giving_bequest_administration/` with `workspace/` already created by the pipeline launcher; treated as DONE per instructions (no index scan, no mkdir).

## Step 2: Generate Scaffold — 2026-08-13T12:00:30.000Z

Scaffold generation complete. All three artifacts are written and the lint verdict is clean.

## Deliverables

All under `/home/ubuntu/github/CodingPRD/tasks/task_1471_planned_giving_bequest_administration/`:

- **SCAFFOLD.yaml** (~1,640 lines): 12 entities (Donor, RateTable, Illustration, GiftAgreement, BeneficiaryDesignation, GiftAsset, AnnuityPayment, ReserveFund singleton, Estate, ProbateMilestone, Fund, ValuationRun), 12 state machines (cyclic: ACTIVE⇄SUSPENDED, PROBATE_OPEN⇄CONTESTED, DUE⇄DEFERRED, REJECTED→SUBMITTED, FROZEN⇄ACTIVE; parallel axes on Donor; posture-driven ReserveFund), 2 OCC concurrency rules (amend, reserve adjustments), 8 calculations (pinned formulas, rounding order, evaluation order), 29 priority-ordered validations, 50 endpoints (incl. `POST /giving/_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` startup default), 32 errors, 5 opaque roles with segregation-of-duties anchors.
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 23 instances, every §0.5 rule ≥2 (dual_variant_calc×3 across GiftAgreement/ReserveFund/GiftAsset domains; combinatorial_formula×3 spanning modes (a) joint-life deduction /(b) per-payment rounding 199800 vs naive 199802 /(c) reserve-gate evaluation order; plus non-linear machines, depth-4 death cascade and depth-3 valuation cascade, 3 distinct priority-conflict category pairs, 3 boundary metrics, 3 cross-entity pairs, half-open vs closed interval overlap, cash-balance vs obligation-mass invariants). All formula asserts are precomputed literals (e.g., reserve requirement 7,570,148¢; joint deduction 2,313,774¢).
- **SCAFFOLD_CORNER_DESIGN.yaml**: 67 instances across all nine taxonomy sections (entities 9, state_machines 12, calculations 6, validations 17, endpoints 4, errors 8 stubs, rbac 5, cross_cutting_complexity_layers 5, consistency_model 2), with `excluded_because` stubs citing §1.8 instances where coverage overlaps.

## Verification performed

- `scaffold_lint.py`: **clean lint** — 741 structured calls across both design files conform to §1.5; all FKs reverse-reachable.
- Mechanical audits beyond the linter: zero unbound `${var}` placeholders; instance names unique across the union (91 total); all 32 error codes triggerable; no forbidden concurrency vocabulary; contiguous validation priorities 1–29; both OCC endpoints satisfy the hard constraints.
- A gate-arithmetic replay script re-executed every `execute` in all 81 active instances against the pinned formulas: every success path passes remainder/exhaustion gates, and the intended failures land on the intended error (this audit caught and fixed a systemic issue where age-70/600bps annuities would have unexpectedly failed the 10% remainder test — all CGA/CRUT instances moved to age 80, literals recomputed).

Notable design decisions: synthetic deterministic actuarial model (terminal age 100, annuity-immediate factor, full-precision factors with pinned round-half-up points); exhaustion limit set to 85% (tighter than the 90% remainder ceiling) so both regulatory tests are independently reachable; removed two initially-drafted error codes (`ERR_AGREEMENT_NOT_ACTIVE`, `ERR_SCHEDULE_ALREADY_EXISTS`) that proved unreachable under the state machines.

## Step 3: Copy Shared Files — 2026-08-13T12:04:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1471_planned_giving_bequest_administration/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T12:29:00.000Z

PRD generated and verified. All checks pass.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1471_planned_giving_bequest_administration/workspace/PRD.md` (363 lines)

**What was produced:** A prose PRD for the planned-giving/bequest administration domain with a domain-derived skeleton — §2 has 10 subsections (roles/SoD, verbatim response envelope, pagination, logical clock + sweeps, common resource properties, precision/pinned rounding order, rate-table windows and pinning, reserve posture with booked-vs-projected bases, OCC, and a 29-step validation priority narrative), §3 has 9 workflow subsections (donor axes + death cascade, rate tables + illustrations, agreement drafting/execution gates, designation paperwork, asset receipt/liquidation, payment schedules, estates/probate/waterfall, funds, valuation runs + reserve compliance), §4 has all 50 endpoints in a 4-column table, §5 has all 32 errors in a 2-column table. The withheld design files were never opened.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + endpoints input/query/path identifiers: 107 required, 107 present, 0 missing
  (verified mechanically: yaml-parsed scaffold identifiers diffed against backticked PRD tokens)
Status: PASS

Rule coverage check:
- validations[] with priority: 29 checked, 29 expressed in §2.10 ordered prose + per-workflow triggers, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (amend/expected_gift_agreement_version, adjustments/expected_reserve_fund_version, ERR_STALE_VERSION 412), 0 missing
- state_machines[].transitions: 45 checked, 45 fully expressed (incl. death-cascade HOPs 1-4, valuation HOPs 1-4, liquidation CGA/estate branches, VERIFY auto-supersede, sibling branches with equal density), 0 missing
- calculations[]: 8 checked, 8 fully expressed in precise prose (annuity split w/ no true-up, deduction factor math, remainder/exhaustion bands, reserve requirement 600bps/110%, floored coverage at 10000bps inclusive, securities FMV basis selection, estate waterfall conservation, revaluation, legacy threshold 10000000), 0 missing
- validations[] conditions: 29 checked, 29 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (clock sweeps, lazy payment sweep on read, retire-vs-execute pin nuance, per-action role splits), 0 missing
- entities[].fields[] structured content: defaults (QUARTERLY, lives=1, UNRESTRICTED, document_received=false, liquidation_costs_cents=0, minimum_endowment_cents=2500000, CGA_RESERVE singleton) and nullability semantics expressed, 0 missing
- sibling-branch symmetry: all parallel branches (4 vehicles, 4 frequencies, 3 asset kinds, 2-lives factor, lapse reasons, milestone/asset gates) rendered with equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 723
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 block is byte-identical to the canonical `section-2.2-response-structure.md`; no pseudocode operators (`==`, `>=`, `+=`, …) or fuzzy quantifiers anywhere in §1–§3; all 5 role names, 32 error IDs, 50 endpoint paths, and every state/enum value from the scaffold appear verbatim. One scaffold inconsistency noted and resolved in favor of the ordered validations table: illustration creation with no covering ACTIVE rate table is written as `ERR_RATE_TABLE_NOT_ACTIVE` (validation priority 18), reserving `ERR_NO_ACTIVE_RATE_TABLE` for valuation-run posting (priority 20), rather than the endpoint description's conflicting label.

## Step 6: Generate Implementation — 2026-08-13T13:42:40.000Z

Implementation complete. Summary below.

## Files created (all under `/home/ubuntu/github/CodingPRD/tasks/task_1471_planned_giving_bequest_administration/workspace/implementation/`)

- `start.sh` — executable; guarded dependency install (`python3 -c "import flask"` check, no reinstall on per-test reboots), `exec python3 app.py` in foreground, `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask
- `app.py` — Flask entry, blueprint registration, envelope-shaped error handlers (404/405/500)
- `store.py` — in-memory dict stores (empty at boot), logical clock starting exactly `2026-08-01T00:00:00Z`, PRD-mandated ReserveFund singleton (`CGA_RESERVE`, balance 0, SOLVENT) — the only startup-instantiated record; no entity seeding
- `errors.py`, `envelope.py` (exact scaffold envelope: `meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`, error body `error_id`/`message`), `security.py` (`X-User-ID`/`X-User-Role`, 5 roles, per-action role splits), `validate.py` (schema/enum/type/unknown-field → `ERR_INVALID_REQUEST`), `calc.py` (actuarial math, round-half-up via Decimal, floored coverage), `giftcalc.py`, `domain.py` (live-derived fields, reserve recompute with pinned evaluation order, sweeps, funding re-evaluation)
- `routes/`: clock, donors, rate_tables, illustrations, agreements, designations, assets, payments, reserve, estates, milestones, funds, valuations

## Endpoints: 50/50 implemented
Clock set; donors CRUD + record-death + legacy-society-transition; rate-tables create/read/transition; illustrations create/list/read/book; gift-agreements create/list/read/amend(OCC)/execute/transition/terminate/settle/generate-payment-schedule; beneficiary-designations create/list/read/transition; gift-assets create/list/read/transition; annuity-payments list/read/transition; reserve-fund read/adjustments(OCC); estates create/list/read/transition; probate-milestones create/list/read/transition; funds create/list/read/transition; valuation-runs create/read/post.

## State machines: 11
Donor (parallel vital + legacy axes), RateTable, Illustration (incl. self-referential supersede), GiftAgreement (10 states, cyclic SUSPEND/RESUME, system EXECUTED→FUNDED funding-threshold auto-transition), BeneficiaryDesignation (incl. REJECTED→SUBMITTED resubmit loop, VERIFY auto-supersede), GiftAsset, AnnuityPayment (DUE↔DEFERRED loop), ReserveFund (SOLVENT↔RESERVE_DEFICIENT auto), Estate (CONTESTED detour, one-way alternate-valuation election), ProbateMilestone, Fund (auto-ENDOWED at inclusive minimum), ValuationRun.

## Calculations: 8
Annuity amounts (fixed-at-funding vs annually-revalued CRUT, per-payment rounding, no true-up), charitable deduction (full-float annuity-immediate factor, 10% remainder test, 85% CRT_ANNUITY exhaustion test), CGA reserve requirement (600bps/110%), reserve coverage (booked/projected bases, floored bps, 10000bps inclusive gate), securities FMV (DOD/ALT basis selection), estate distribution waterfall (per-asset net first, exact subtraction), actuarial revaluation (whole-year age advancement, corpus updates, payment recompute hops), legacy recognition threshold (10000000 inclusive).

## Verification
- Boots cleanly from a fresh process: `PORT=14719 bash start.sh` → 200 on `/giving/reserve-fund` in ~2.5s; fresh-boot state verified empty (donors 0, reserve balance 0/SOLVENT/v1, clock reset).
- 4 custom smoke suites (~150 assertions) all pass: full lifecycle, death cascade, valuation revaluation with corpus updates, error-catalog coverage, boundary values (payout 499/500/5000/5001, coverage 9999/10000, funding threshold inclusivity, exhaustion band).
- Real benchmark run: `prd-bench-local-run --isolation per-test-server` → **100/102 passed**. The 2 failures (`test_13_death_cascade` x2) are a test-suite internal contradiction: `test_13` line 26 wraps `generate_payment_schedule` in `validate_success` with default expected 200, while `test_08_payment_schedules.py:79` explicitly asserts `validate_success(resp, 201)` for the identical call, and PRD §4 plus the scaffold endpoint table both mandate **201** for schedule generation. I kept 201 per the PRD; a line-by-line replication of the failing scenario confirms every functional assertion in both tests passes (maturity cascade, 80 lapsed payments, reserve flip to SOLVENT, auto-created estate fields).

## Step 5: Generate Unit Tests — 2026-08-13T13:47:48.000Z

Generation complete. Summary of what was built and verified:

## Test counts
- **Queue A (Difficulty, §1.8): 23/23 instances covered, 47 tests** (≥2 per instance; `rate_table_half_open_window_adjacency` has 3).
- **Queue B (Corner, §1.9): 58/58 non-stub instances covered, 58 tests** (exactly 1 each).
- **Total: 105 tests** across 15 files. All 10 `excluded_because:` stubs left untranslated; each stub's `difficulty_instance` cross-reference was verified to resolve (8 error stubs → their owning difficulty instances; `bequest_matures_on_death_skipping_funding` and `immediate_consistency_death_cascade_atomic` → `donor_death_maturity_cascade`).

## Instances skipped
None. Every non-stub instance passed the PRD-first two-condition filter — the PRD (§2.10's explicit validation priority chain, §2.8's two coverage bases, §3.9's four-hop revaluation cascade, etc.) verbatim-covers every asserted rule.

Two sub-assertion adjustments (not skips): (1) `version == 1` initial-value assertions in `donor_create_applies_defaults` / `reserve_fund_singleton_default_read` were dropped — PRD §2.5 says version "starts at creation" without pinning 1 vs 0, failing unique derivability; (2) in `withdrawn_agreement_is_terminal`, the amend carries the *current* version so the state gate (not OCC) is the failing check — with a stale version the PRD's own priority order (#5 before #6) would return `ERR_STALE_VERSION`, not the asserted `ERR_INVALID_STATE`. Also note: difficulty instance `reserve_adjustment_contribution_withdrawal_neutral`'s yaml asserts an intermediate balance of 9584789 after +500000 on 7570148; the PRD-derived value is 8070148 ("A contribution adds the amount to `balance_cents`"), so the test asserts the PRD-derived 8070148 and the invariant (return to exactly 7570148, version +2) verbatim.

## Files created
- `test_helpers/`: `types.py` (12 TypedDicts + 17 enums), `api_client.py` (44 endpoint methods), `api_errors.py` (32 error IDs, registered via `set_error_http_status_map`), `constants.py` (PRD thresholds + formula-derived expected values, all hand-verified against the PRD's actuarial formulas: e.g. reserve requirement 7570148, deduction 2313774/776529/1741101, revaluation liability 8701431/7251193), `factories.py`, `assertions.py`, `test_users.py` (5 opaque-role header sets + per-user builders for SoD), `fixtures.py` (lifecycle ladders: draft → verified → executed → funded → active; reserve OCC helpers; estate/probate/fund/valuation composites), `__init__.py` barrel.
- `test_suite/`: `conftest.py` + `test_01_…_test_15_*.py` grouped by concern (donors, legacy society, rate tables, illustrations, execution gates, designations, assets, payment schedules, reserve fund, estates, funds, valuation runs, death cascade, security/RBAC/SoD, OCC & queries).

## Mechanical self-checks run
- **Tag coverage audit** (AST walk of all 105 tests): every docstring ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line; all tags resolve to real instances; per-instance minimums met; stubs have zero tests.
- **Verbatim citation audit**: every quoted span ≥8 chars in every test docstring verified as a whitespace-normalized substring of `PRD.md` (this caught and fixed 4 bold-marker/elision mismatches before the final pass).
- **Import sanity**: `test_helpers` and all test modules import cleanly with the framework on `PYTHONPATH`; no unused imports (pyflakes clean outside intentional barrel re-exports); no "scaffold" references in generated code.
- **Syntax/collection**: `py_compile` on all files; `pytest --collect-only` collects exactly 105 tests with no errors.

The audit script was a dev-only tool and was removed after the final pass; only `test_helpers/` and `test_suite/` remain as deliverables.

## Step 7: Run Tests and Iterate — 2026-08-13T14:15:00.000Z

All 8 rounds are clean: 105/105 passed in every round.

## Summary

- **Iterations run:** 2 (iteration 1: 103/105 in all 8 rounds — same 2 failures deterministically; iteration 2: 105/105 in all 8 rounds, zero flakiness).

- **Tests deleted:** none.

- **Fixes applied to `test_suite/`:** one.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1471_planned_giving_bequest_administration/test_suite/test_13_death_cascade.py`, `_death_cascade_scenario` (line 26): the setup wrapped `api.generate_payment_schedule(...)` in `validate_success` with the framework-default expected status 200, tripping "Expected 200, got 201" in both cascade tests. Changed to `validate_success(..., 201)`. PRD §4 (line 273) verbatim covers the rule — "Operations that create a new resource — … and generating a payment schedule — return `201 Created`" — and uniquely determines 201; the sibling test `test_08_payment_schedules.py::test_schedule_generation_structure` already asserts 201 for the identical call. This was the known starting signal, adjudicated per STEP 2 as a test bug (assertion contradicted PRD); the implementation's 201 was PRD-faithful and untouched.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `implementation/`:** none — the implementation was already PRD-faithful; the only failures were the test-suite's status-code mismatch above.

## Step 8: Finalize PRD — 2026-08-13T14:20:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1471_planned_giving_bequest_administration/workspace/PRD_FINALIZED.md` is a byte-identical copy of `PRD.md` — zero edits.

**Zero edits made.** The single `<step_7_diff>` item was a pure test-suite bug (test expected HTTP 200 where the PRD mandates 201), not a PRD silence or PRD/impl mismatch, so no PRD patch was warranted.

**Verification performed (in lieu of per-edit search logs):**
- PRD §4, line 273 verbatim: "Operations that create a new resource — registering a donor, creating a rate table, illustration, agreement, designation, asset, estate, milestone, fund, or valuation run, booking an illustration into a new agreement, **and generating a payment schedule** — return `201 Created`." This uniquely determines 201 for schedule generation.
- PRD §4 endpoint table, line 298: `POST /giving/gift-agreements/{agreement_id}/generate-payment-schedule` is listed under §4, so the blanket 201 rule applies to it; no endpoint-specific exception exists anywhere in the PRD (grep over all "payment schedule" mentions: lines 5, 95, 228, 273, 298 — none assign a different status).
- Implementation route: `workspace/implementation/routes/agreements.py:529` — `generate_payment_schedule` returns `success([view(p) for p in created], 201)`. Matches the PRD exactly.

PRD and implementation were already aligned; only the test's expected-status argument contradicted both, and that was fixed in `test_suite/`. Editing the PRD to restate what it already pins verbatim would have been a manufactured edit.

**Line counts / %-delta:** PRD.md = 363 lines; PRD_FINALIZED.md = 363 lines; delta = 0 (0.0%); `cmp` confirms byte-identical.

## Step 9: Complete PRD — 2026-08-13T14:50:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1471_planned_giving_bequest_administration/workspace/PRD_COMPLETED.md` is produced — a minimal inline patch over PRD_FINALIZED.md, pinned to `implementation/`.

**Size:** PRD_FINALIZED.md 363 lines / 59,368 chars → PRD_COMPLETED.md 363 lines / 61,945 chars. Char-delta: **+2,577** (17 in-place paragraph hunks; no sections added, no lines added or removed).

**Counts:** 17 ambiguity-pins, 3 mismatch-revisions (20 changes total).

**Changes (one per bullet):**
- §2.3 — revise — ambiguity — pagination: out-of-range `limit` clamped into [1,100], negative `offset` clamped to 0, non-integer `limit`/`offset` rejected with `ERR_INVALID_REQUEST` (400) — implementation/domain.py:199-217
- §2.3 — revise — ambiguity — list `created_at` ties broken by creation order (insertion sequence) — implementation/domain.py:35-36
- §2.3 — revise — ambiguity — payment list sorted by `period_index` ascending only when filtered by `gift_agreement_id`; unfiltered follows default `created_at` ordering — implementation/routes/payments.py:30-34
- §2.4 — revise — ambiguity — clock set accepts any `to_iso8601` instant unconditionally; no monotonicity constraint — implementation/routes/clock.py:18-19
- §2.5 — revise — ambiguity — `version` starts at 1 at creation — implementation/store.py:57
- §2.7 — insert — ambiguity — a `funding_month` denotes the first instant of that month (00:00:00Z day 1) for every coverage/elapsed-time evaluation — implementation/validate.py:43-45, domain.py:250-257, calc.py:70-76
- §2.10 (item 29) — revise — mismatch — schema conformance is enforced at body-parse time: creation endpoints, both shared transition endpoints, clock-set, reserve-adjustment, and valuation-run window check validate the body before reference resolution (shared transitions also before the per-action role check); amendment parses after path resolution but before `fund_id`/OCC; remaining action endpoints resolve the path id first; auth always runs first — implementation/validate.py:48-99 plus per-route handler ordering (e.g., routes/illustrations.py:29-45 vs routes/estates.py:87-97)
- §3.1 — revise — ambiguity — `date_of_birth` accepts an ISO 8601 date or datetime — implementation/validate.py:13-29
- §3.1 — revise — mismatch — legacy ENROLL on a non-LIVING donor yields `ERR_DONOR_STATE_MISMATCH` (409), not `ERR_LEGACY_SOCIETY_INELIGIBLE` (which is reserved for the missing-documented-gift failure) — implementation/routes/donors.py:149-162
- §3.1 — insert — ambiguity — recording death for an already-`DECEASED` donor is rejected with `ERR_INVALID_STATE` (409) — implementation/routes/donors.py:76-77
- §3.2 — revise — ambiguity — `lives` outside 1–2 rejected with `ERR_INVALID_REQUEST` (400); the `annuitant_2_age` requirement applies to annuity vehicles only (a `BEQUEST` carries no annuitant-age requirements) — implementation/routes/illustrations.py:64-66, giftcalc.py:22-42
- §3.3 — insert — ambiguity — amend: explicit null `fund_id` detaches the fund; other amendable fields treat explicit null as not supplied — implementation/routes/agreements.py:203-213
- §3.3 — insert — ambiguity — annual annuity formula pinned: round-half-up(`gift_amount_cents` × `payout_rate_bps` / 10000) — implementation/calc.py:54-56, giftcalc.py:58
- §3.3 — revise — ambiguity — `remainder_value_cents` pinned to zero for a `BEQUEST` at execution (not corpus − 0) — implementation/routes/agreements.py:325-330
- §3.5 — revise — ambiguity — the alternate-valuation price pair is accepted and stored on any securities receipt but applied only for estate-linked assets after the election — implementation/routes/assets.py:157-160, 27-42
- §3.5 — insert — ambiguity — estate-linked asset RETURN carries no estate-status precondition — implementation/routes/assets.py:221-233
- §3.6 — revise — ambiguity — first `due_date` falls one frequency period after the first day of the agreement's `funding_month`; every `due_date` is the first of a month — implementation/routes/agreements.py:505-513
- §3.6 — insert — ambiguity — schedule generation returns `201 Created` with `data` carrying the created payments as an array in `period_index` order — implementation/routes/agreements.py:529
- §3.6 — revise — mismatch — cascade `lapse_reason` vocabulary is `DONOR_DEATH` or `TERMINATION` only; the PRD-listed `MATURITY` reason is never stamped — implementation/routes/payments.py:107, donors.py:103, agreements.py:430
- §3.7 — revise — ambiguity — BEGIN_DISTRIBUTION's `administration_costs_cents`/`specific_bequests_cents` each default to zero when omitted; an estate carries both at zero and a null `residual_to_university_cents` until distribution begins — implementation/routes/estates.py:56-59, 189-190

Everything else in the PRD (endpoint table, role assignments, gate chains and their §2.10 priority order for domain checks, actuarial/reserve formulas, cascades, envelope shapes, error catalogue) was walked endpoint-by-endpoint against the implementation and already matched uniquely.
