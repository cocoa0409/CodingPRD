# Worklog — task_1921_defined_benefit_actuarial_valuation

## Step 1: Create Task Directory — 2026-08-15T00:52:00.000Z

Pre-created by pipeline runner: `tasks/task_1921_defined_benefit_actuarial_valuation/` and `workspace/` verified present and empty. Index scan skipped per invocation instructions.

## Step 2: Generate Scaffold — 2026-08-15T01:40:00.000Z

Generated SCAFFOLD.yaml (§1.0–§1.7), SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8, 21 instances across all 9 rules), SCAFFOLD_CORNER_DESIGN.yaml (§1.9, 48 instances across 8 sections). Complexity profile: compliance_audit + ledger_reconciliation; segregation_of_duties role model; OCC on Plan.version for certify and election-create. All formula-derived asserts pre-computed as literals (pinned TEST_TABLE_4AGE mortality, 4dp annuity factors, round-then-sum aggregation). scaffold_lint.py: VERDICT clean lint (62 endpoints, 15 entities, 886 calls scanned).

Design adjudications (verbatim from subagent): (1) ERR_MAX_DEDUCTIBLE_EXCEEDED removed as unreachable; (2) PBGC amend precondition redefined as supersession-driven; (3) 62 endpoints justified by lint-enforced FK reverse-reachability; (4) deterministic Fraction/Decimal-computed fixtures; (5) OCC on Plan.version for certify + election-create.

## Step 3: Copy Shared Files — 2026-08-15T01:40:30.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-15T01:56:00.000Z

PRD generation complete. Final summary below.

**Output path:** `/home/ubuntu/github/CodingPRD/tasks/task_1921_defined_benefit_actuarial_valuation/workspace/PRD.md`

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications — 2.1 RBAC (headers, 5 roles, identity semantics per role), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Common Resource Properties (incl. ContributionPayment exception: only `id` + `created_at`), 2.5 Logical Clock & Calendar-Pinned Dates, 2.6 Precision & Rounding, 2.7 OCC, 2.8 Validation Order & Nested Resolution, 2.9 Segregation of Duties & Enrollment
- §3 Business Logic — 3.1 Plan Onboarding/Credit Balances/Termination, 3.2 Census Collection & Screening, 3.3 Assumption Sets & Review Loop, 3.4 Asset Roll-Forward & Smoothing Corridor, 3.5 Valuation Runs/Annuity Factors/Accruals/Aggregation, 3.6 Certification/AFTAP/Posture cascade, 3.7 Contribution Demands/Payments/Delinquency, 3.8 Credit-Balance Elections & Revocation, 3.9 PBGC Premiums & Disclosure
- §4 Endpoint Definitions (62 rows, 4 columns)
- §5 Error Code Catalogue (23 rows, 2 columns)

**Line count:** 294

**Coverage-audit verdicts (all PASS):**

```
Field coverage check (Contract 1):
- entities[].fields + endpoint inputs/query params: 98 required, 98 present, 0 missing
Status: PASS

Rule coverage check (Contract 2):
- validations[] priority ordering: 22 rules, relative order expressed as explicit chain in §2.8 (SoD before enrollment; body-validation lowest)
- concurrency_rules[] OCC: 2 checked, 2 expressed (certify + election create, expected_plan_version, ERR_STALE_VERSION/412)
- state_machines[].transitions: 29 checked, 29 fully expressed (preconditions + error ids + side effects, incl. 4-hop certify cascade and all 7 demand transitions)
- calculations[]: 12 checked, 12 fully expressed in precise prose (annuity factor with survival-product narration + calibration anchors; pinned per-participant-then-sum rounding; corridor; waterfall with conserved-quantity invariant; certified vs presumed AFTAP branches; premium cap equality binding)
- validations[] conditions: 22 matchable to error_id in §2/§3 prose (all 23 error ids appear in prose)
- endpoints[].side_effects / applies_to: expressed (enrollment rule enumerated for approve+lock+certify; plan-year mismatch for all 7 create endpoints; uniqueness for reopen/asset-statement/external_ref)
- entities[].fields[] structured content: defaults, bounds, enum domains, null semantics reconstructible from prose
- sibling-branch symmetry: screening outcomes, participant statuses, STANDARD/ALTERNATIVE, corridor FLOOR/CEILING/NONE, presumed-AFTAP branches — equal density
Status: PASS

Path purity check (§3 only, Contract 3):
- backtick tokens scanned: 392
- tokens starting with `/`: 0; bare HTTP-method tokens: 0; method+path tokens: 0
Status: PASS
```

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened, grepped, or referenced.

## Step 5: Generate Unit Tests — 2026-08-15T02:20:00.000Z

Generation complete. Summary of what was produced for `task_1921_defined_benefit_actuarial_valuation`:

**test_helpers/ (Stage 1):** `types.py` (12 status enums + 17 entity TypedDicts), `api_client.py` (48 endpoint methods covering full PRD §4 surface), `api_errors.py` (all 23 error IDs + HTTP map), `assertions.py` (per-entity field assertions + `assert_money`), `factories.py`, `constants.py` (AFTAP tiers 80/60, corridor 0.80/1.20, PBGC rates 100/50/600, excise 10%, amortization /7, clock anchors), `test_users.py` (opaque-role headers + entity-backed Actuary builders), `fixtures.py` (composite lifecycle helpers incl. `setup_certified_plan`), `__init__.py`.

**test_suite/ (Stage 2):** `conftest.py` + 12 test files, **91 test functions**.

**Coverage:** Queue A (Difficulty): 21/21 instances, ≥2 tests each (42+ tests). Queue B (Corner): 48/48 non-stub instances covered. Coverage audit: 0 failures, 0 phantom tags.

**Skipped instances:** None — every instance passed the PRD-first two-condition filter. One nuance: `census_batch_correction_loop`'s final LOCKED assertion assumed the re-posted row replaces the age-64 row, but PRD §3.2 says appended rows extend the batch (no delete pathway) — the two emitted tests split the instance (screening outcome + revision-loop re-entry, then LOCKED via a clean second batch).

**Stage 1/2 self-checks:** all files compile; 91 tests collected; C1 verbatim substring check passes for every docstring; C4 tag format exact; no skip/xfail anywhere.

## Step 6: Generate Implementation — 2026-08-15T02:20:00.000Z

The implementation is complete and fully verified.

**Files written** (under `workspace/implementation/`): `start.sh` (guarded dependency install + `exec python3 app.py`; fresh boot <1s honoring PORT, 0.0.0.0, empty store, clock pinned 2026-08-01T00:00:00.000Z), `requirements.txt`, `app.py`, `db.py` (in-memory store, zero seeding, logical clock), `errors.py` (23 error IDs), `response.py` (meta/response_type/data envelope, pagination), `middleware.py` (5 roles), `validate.py`, `services/core.py` (calculations, serializers, cascades), `routes/` (plans, census, assumptions, assets, runs, funding, filings).

**Coverage:** all 63 endpoints; all 8 state machines (census correction loop, assumption review/reopen, PBGC amend cycle, clock-driven delinquency with one-time 10% excise); all 11 calculations verified numerically against every design anchor (annuity factors at 5%/4%, round-then-sum 639.70, corridor FLOOR/CEILING, AFTAP 59.99 freeze cascade with tentative 6137.29 / max-deductible 96651.50, 80.00 boundary → UNRESTRICTED, PBGC cap equality, dual-variant, pool conservation, satisfaction identity); full validation priority ordering; OCC 412 on certify + election create. ~180 smoke assertions pass on fresh boots.

**Key interpretation decisions:**
1. Participant upload stores all structurally valid rows incl. business-invalid (age 64); screening adjudicates validity. Duplicate external_ref aborts the request with 409.
2. PBGC filing creation allowed from COMPUTED run; CERTIFIED gate fires at /file and disclosure creation.
3. OCC placement after existence/from-state/plan-active, before SoD/enrollment; missing expected_plan_version → ERR_VALIDATION at lowest priority.
4. Presumed AFTAP: pre-April-1 posture pinned UNRESTRICTED regardless of prior value; post-Oct-1 posture ACCRUAL_FROZEN with presumed_aftap_pct = null.
5. Frozen normal-cost zeroing applies to both tentative_minimum and max-deductible cushion basis.
6. Body-referenced nonexistent ids → 404; cross-plan/year → 422 ERR_PLAN_YEAR_MISMATCH; unregistered actuary on approve/lock/certify → ERR_ACTUARY_NOT_ENROLLED.
7. Delinquency evaluated only on clock advancement; election revocation does not bump Plan.version; plan termination voids only DRAFT filings.

Noted inconsistency: difficulty design's `census_batch_correction_loop` final assert (LOCKED with age-64 row still present) is self-contradictory with screening rules; impl follows store-everything + screening-adjudicates semantics, under which that batch correctly remains NEEDS_CORRECTION. (Step 5 split this instance accordingly.)

## Step 7: Run Tests and Iterate — 2026-08-15T03:00:00.000Z

## Summary

**Final state: all 8 parallel rounds pass — 93/93 tests in every round, empty failure union.**

- **Iterations run:** 2 effective sweeps (sweep 1 baseline → fixes → sweep 3 clean; one intermediate sweep was killed externally on the shared host mid-run and discarded, no results written).

- **Tests deleted:** None.

- **Fixes applied to `test_helpers/`:** None.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1921_defined_benefit_actuarial_valuation/test_suite/test_07_contribution_demands.py` — duplicate class name `TestPriorityPairs` (defined at lines 144 and 222); the second definition shadowed the first, silently dropping 2 PRD-verbatim-covered tests from collection (`test_state_beats_fiscal_on_satisfied_demand_payment`, `test_overpayment_rejected_on_open_demand`). Renamed the second class to `TestPriorityPairsNoSideEffects`; collection went from 91 to 93 tests.

- **Fixes applied to `implementation/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1921_defined_benefit_actuarial_valuation/workspace/implementation/services/core.py` — `_auto_transition_demand`: the strict `outstanding < minimum_due` comparison kept a demand `OPEN` after a partial credit-balance election (election 1000 on tentative 2839.98 → outstanding 1839.98 == minimum_due 1839.98 → `OPEN`). PRD §3.7 ("A payment or election that leaves `outstanding_amount` positive but below `minimum_due` moves it to `PARTIALLY_SATISFIED`") plus the revocation clause ("a revocation that restores a positive outstanding amount pulls a `SATISFIED` demand back to `PARTIALLY_SATISFIED`" — the identical numeric configuration) uniquely pin `PARTIALLY_SATISFIED` once any payment/election activity has landed. New rule: outstanding ≤ 0 → `SATISFIED`; `DELINQUENT` sticky while positive; any prior non-OPEN status with positive outstanding → `PARTIALLY_SATISFIED`; birth-state `OPEN` persists only while credit_applied and paid_to_date are both zero. Verified end-to-end via smoke test including the SATISFIED→PARTIALLY_SATISFIED revocation path.

- **Diagnostic notes:** Sweep 1's failure union was exactly one deterministic test (`test_partial_election_moves_demand_to_partially_satisfied`, failed 8/8 rounds). Apparent `FAILED` lines for `test_state_beats_fiscal_no_payment_recorded` in the interleaved console output were artifacts of 8 parallel writers; all 8 authoritative `results.${i}.json` files recorded it passed. No flakiness was observed in the final sweep — every round ran to completion with identical 93/93 results.

## Step 8: Finalize PRD — 2026-08-15T03:12:00.000Z

Done. `PRD_FINALIZED.md` is written with exactly one inline revision.

**Line counts / delta:** PRD.md 294 lines, PRD_FINALIZED.md 294 lines — 0 lines changed (0.0%); the single edit replaces one paragraph in place (§3.7, line 177).

**Changes:**
- §3.7 (demand lifecycle paragraph) — revise — pins the `_auto_transition_demand` rule as implemented: (i) `OPEN` persists only while `credit_applied` and `paid_to_date` are both zero; (ii) any payment/election leaving `outstanding_amount` positive → `PARTIALLY_SATISFIED`, explicitly including the boundary where positive outstanding equals `minimum_due` (the Step 7 failing scenario: election 1000 on tentative 2839.98 → outstanding 1839.98 == minimum_due 1839.98, previously unpinned by "positive but below `minimum_due`"); (iii) zeroing condition widened "at exactly zero" → "at or below zero" to match the `outstanding <= 0` branch (reachable via recertification shrinking `minimum_due` below `paid_to_date`); (iv) `DELINQUENT` explicitly sticky while outstanding is positive across all four recompute triggers; (v) the "pulls `SATISFIED` back" clause widened from revocation-only to "revocation or recertification … never to `OPEN`" — `workspace/implementation/services/core.py:486-504`.

**Test-suite item verdict (no PRD change):** the `TestPriorityPairs` duplicate-class rename is a pure test-collection bug; the two shadowed tests assert behavior the PRD already pins verbatim (§2.8/§3.7 state-gate-before-fiscal and §3.7 `ERR_OVERPAYMENT`) and the implementation already conforms (`routes/funding.py:240-252`). No PRD silence, no edit.

**Per-edit pre-edit search log (edit 1 of 1):**
- (a) Subject: contribution-demand status auto-transitions on recompute.
- (b) Impl paths enumerated and read: `services/core.py:486-504` (`_auto_transition_demand`); `services/core.py:439-483` (`recompute_demand`); `services/core.py:507-519` (`evaluate_delinquency`); all four recompute callsites — `routes/runs.py:225` (certification cascade), `routes/funding.py:139` (election creation), `routes/funding.py:185` (revocation), `routes/funding.py:276` (payment posting); plus `routes/plans.py:156` (clock endpoint). Cross-checked PRD §2.5, §2.8, §3.6 hop 4, §3.7, §3.8.
- (c) Wording adjustments: scoped the payment/election sentence to OPEN/PARTIALLY_SATISFIED demands; named only a credit-balance election as producer of the outstanding == minimum_due boundary; phrased OPEN-persistence one-way; scoped "recomputed by the waterfall's reverse pass" to revocation only.

## Step 9: Complete PRD — 2026-08-15T03:30:00.000Z

**File produced:** `workspace/PRD_COMPLETED.md`

**Source vs. output:** `PRD_FINALIZED.md` (294 lines / 50,780 bytes) → `PRD_COMPLETED.md` (294 lines / 54,825 bytes); char delta **+3,998** (+4,045 bytes due to multibyte em dashes). All edits in-paragraph; no sections/paragraphs/lines added or removed (22 existing lines revised in place).

**Counts:** 19 ambiguity-pins, 5 mismatch-revisions (24 distinct behavior pins across 22 edited lines).

**Changes (section — insert|revise — ambiguity|mismatch — what changed — impl ref):**

- §2.3 — insert — ambiguity — out-of-range/non-integer `limit`/`offset` → `ERR_VALIDATION` 400; `created_at` ties broken by request-arrival order — response.py:64-97
- §2.4 — insert — ambiguity — `updated_at` equals `created_at` at creation; `version` starts at 1 — services/core.py:57-65
- §2.5 — revise — ambiguity — clock is *set* (forward or backward), unparseable `to_iso8601` → `ERR_VALIDATION` — routes/plans.py:145-157
- §2.7 — insert — ambiguity — staleness check ordering (after plan-active gate, before SoD/enrollment/business rules); non-integer `expected_plan_version` → `ERR_VALIDATION` immediately; absent one → `ERR_VALIDATION` only at body-well-formedness stage — routes/runs.py:155-172, routes/funding.py:74-117
- §2.8 — insert — ambiguity — body-carried identifiers naming nonexistent resources → `ERR_NOT_FOUND` before business rules — routes/runs.py:46-55, routes/filings.py:42-45
- §2.8 — revise — **mismatch** — plan-active gate blanket statement carved out: auditor acknowledgment of a disclosure report remains permitted under a `TERMINATED` plan — routes/filings.py:233-242
- §2.9 — insert — ambiguity — `X-User-ID` naming no registry actuary treated as non-`ENROLLED` → `ERR_ACTUARY_NOT_ENROLLED` — routes/assumptions.py:27-31
- §3.1 — insert — ambiguity — termination refused with outstanding demand → `ERR_INVALID_STATE` 409 — routes/plans.py:98-100
- §3.1 — revise — **mismatch** — "any mutation scoped to a TERMINATED plan" carved out for auditor acknowledgment — routes/filings.py:233-242
- §3.1 — insert — ambiguity — `status` filter accepts exactly `ACTIVE`/`TERMINATED`, else `ERR_VALIDATION` — routes/plans.py:74-76
- §3.2 — revise — **mismatch** — upload tolerance: structurally sound rows (incl. business-defective ones) all persisted with 200; business defects surface only at screening; structural defects abort the whole request with `ERR_VALIDATION`, checked *before* `external_ref` uniqueness — routes/census.py:89-163
- §3.2 — insert — ambiguity — repost to `NEEDS_CORRECTION` also resets `error_count` to zero — routes/census.py:158-159
- §3.2 — insert — ambiguity — `screening_errors` entries carry `participant_id`, `external_ref`, `message` — routes/census.py:204-209
- §3.4 — insert — ambiguity — asset valuation with no statement for the plan year → `ERR_NOT_FOUND` 404; valuation carries `asset_statement_id` and is not unique per plan year — routes/assets.py:112-131
- §3.5 — insert — ambiguity — runs not unique per references; `funding_target`/`normal_cost` null until computation — routes/runs.py:81-96
- §3.6 — insert — ambiguity — `aftap_pct` = 0.00 when `funding_target` is zero — routes/runs.py:181-184
- §3.6 — insert — ambiguity — on/after Oct 1 (pre-certification) `presumed_aftap_pct` reads null — services/core.py:298-300
- §3.7 — revise — ambiguity — `maximum_deductible` cushion basis adds the *normal-cost component* (zeroed when frozen), not raw `normal_cost` — services/core.py:472
- §3.7 — insert — ambiguity — `excise_accrued` reads 0.00 until a delinquency transition assesses it — routes/runs.py:219, services/core.py:518
- §3.7 — revise — **mismatch** — "begins `OPEN`" qualified: a demand whose first computation leaves no positive outstanding is `SATISFIED` from birth — services/core.py:486-489
- §3.8 — insert — ambiguity — `contribution_demand_id` nonexistent or cross-plan → `ERR_NOT_FOUND`; election against `SATISFIED` demand → `ERR_INVALID_STATE` — routes/funding.py:60-69
- §3.9 — revise — **mismatch** — filing creation does *not* require a `CERTIFIED` run; the certified gate applies at file/re-file time and at disclosure-report creation — routes/filings.py:51-58, 114-117, 179-181
- §3.9 — insert — ambiguity — amend retains the filing's `premium_method` and re-copies `plan_year` from the newly certified run — routes/filings.py:138-140
- §3.9 — insert — ambiguity — acknowledgment explicitly exempt from the plan-active gate — routes/filings.py:233-242

Key cross-checks: §3.9 filing-creation revision confirmed by test_09; §3.1 termination error pin by test_07; §3.8 election-on-SATISFIED pin by test_08.

**Final verification (orchestrator):** workspace/PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, INSTRUCTION.md all present; 8 results files all 93/93; test_suite collects 93 tests. Pipeline complete.
