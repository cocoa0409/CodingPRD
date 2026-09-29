# Worklog — task_2161_multiemployer_taft_hartley_fund

## Step 1: Create task directory — 2026-08-27T04:47:08.250Z

Created `tasks/task_2161_multiemployer_taft_hartley_fund/` and `tasks/task_2161_multiemployer_taft_hartley_fund/workspace/`. Index 2161 = highest existing (2160) + 1.

## Step 2: Generate scaffold — 2026-08-27T05:57:58.152Z

All three scaffold artifacts are generated and lint-clean.

## What was produced

`/home/ubuntu/github/CodingPRD/tasks/task_2161_multiemployer_taft_hartley_fund/`
- **`SCAFFOLD.yaml`** (§1.0–§1.7, 1401 lines) — no design keys inside
- **`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** (§1.8, single `scaffold_difficulty_design` key)
- **`SCAFFOLD_CORNER_DESIGN.yaml`** (§1.9, single `scaffold_corner_design` key)

## Design shape (Expert+, per "harder than expert level")

- **Profile**: ledger_reconciliation × compliance_audit; `entity_topology: flat`, `state_machine_shape: parallel`, `role_model: segregation_of_duties`, `consistency_model: immediate`; layers = OCC, cascading side effects, dual-variant calc, ops-run checkpoint.
- **Surface**: 15 entities, 9 state machines, 10 calculations, 15 ordered validation tiers, 51 endpoints, 53 errors, 5 roles, 2 OCC concurrency rules.
- **`api_prefix: ""`** with flat top-level collections; all 21 FKs have reverse-reachability GETs (sub-resource or filtered-list).
- Test-driving endpoints: `POST /_clock/set_current_utc` (default clock pinned at `2026-08-01T00:00:00Z`) and the business ops-run `POST /funds/{id}/run-collections`.

## Difficulty coverage (§0.5, 9 rules × 2 = 18 instances)

- **dual_variant** on two different entity domains: `delinquency_charges` (STATUTORY 434494 vs PLAN_SCHEDULE 397404 cents) and `pension_credit_accrual` (HOURS_BASED 0.00 vs ELAPSED_TIME 1.00 credit on identical 151.30 hours).
- **combinatorial** in two different modes: (b) per-line-then-sum rounding pinned at 357668 vs the wrong 357669; (c) the 20-year-cap circular evaluation order (net stays 60000000, capped collapses to 1651000).
- **non-linear machines** on different entities: ContributionReport's parallel `filing_status × payment_status` axes, and PayrollAudit's `FINDINGS_ISSUED → IN_FIELDWORK` dispute cycle with a 3-round limit.
- **cascades**: depth-4 audit-finalize chain (mint AUDIT report → credit hours → mint CoverageMonth → flip eligibility) and depth-4 run-collections chain (report DELINQUENT → strikes → employer SUSPENDED → fund count).
- **priority conflicts** on different category pairs: state(45) vs fiscal(62), and safety(50) vs constraint(60).
- **boundaries** on different metrics/endpoints: de-minimis phase-out at exactly 10000000 cents, and `vesting_year_earned` at exactly 870.00 hours.
- **cross-entity**: ContributionReport→Employer and WithdrawalAssessment→Fund.
- **temporal overlap** with different interval semantics: closed-month audit-interval intersection (adjacency allowed) on Employer, vs aggregate forward-window coverage horizon on Participant.
- **compensating invariants** on different conserved quantities: credited hours across amendment supersede, and the employer money ledger across an LD waiver.

## §1.9 breadth

49 instances across all 8 applicable guide sections (3 are `excluded_because` stubs pointing at named §1.8 instances). Every one of the 53 catalogued errors is referenced by at least one design instance.

## Verification run

All numeric asserts were computed in Python against the pinned formulas (contribution rounding, interest/LD both bases, allocation fractions to 10 dp, de-minimis phase-out, schedules and installment tails, coverage/bank replay, date arithmetic) and written in as literals.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    51
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     46
  Calls scanned (§1.8+§1.9):  647

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Additional self-checks passed: unique instance names across both files, all `excluded_because` targets resolve, all `grounds` refs resolve into §1.1–§1.7, zero forbidden concurrency vocabulary, no design keys inside `SCAFFOLD.yaml`, endpoint roles ⊆ RBAC matrix, every role carries an `identity:`.

**Constraint honored**: no sibling task under `tasks/` was listed, read, or grepped. Only the skill's own `SKILL.md`, `references/claim-extraction-guide.md`, `scaffold_lint.py`, and two of its bundled `examples/` files (for `api_prefix` convention only) were consulted.

## Step 3: Copy shared files — 2026-08-27T05:58:19.839Z

Copied `./INSTRUCTION.md` → `tasks/task_2161_multiemployer_taft_hartley_fund/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-27T06:10:30.122Z

The PRD is complete and written to `/home/ubuntu/github/CodingPRD/tasks/task_2161_multiemployer_taft_hartley_fund/workspace/PRD.md` (398 lines, ~92 KB), built incrementally in five append passes — no truncated tail, document ends at the §5 error table with no audit footer.

**Structure** — §1 Introduction (3 paragraphs); §2 with 10 domain-derived subsections (RBAC, the fixed response envelope, pagination, resource identity/version, the logical clock, money & rounding discipline, stale-parent OCC, a 15-rung Order of Rejection ladder, cascade discipline, resource collections/path resolution); §3 with 10 workflow subsections (chartering, joint board & motions, report intake & pricing, posting/supersession/eligibility replay, pension accrual & breaks, payment axis & delinquency, payroll audits, reciprocity, withdrawal liability, collections run); §4 endpoint table (4 columns, 51 rows); §5 error table (2 columns, 47 rows).

**Hard Contract Reports (transcript only, not written to disk):**

```
Field coverage check:
- entities[].fields: 125 required, 125 present, 0 missing
- endpoints[].request_body / input / output keys (incl. unreported_hours, expected_employer_version, expected_fund_version): 54 required, 54 present, 0 missing
- endpoints[].query_params: 38 required, 38 present, 0 missing
- endpoints[].path_params: 1 required, 1 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 15 checked, 15 expressed in prose (§2.8 explicit first-failure-wins ladder), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 39 checked, 39 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed (all constants embedded in business context; all 8 variants rendered), 0 missing
- validations[] conditions: 47 error ids checked, 47 matchable to a trigger in §2/§3 narrative, 0 missing
- endpoints[].side_effects / applies_to: all endpoint side-effect lists and all 6 multi-endpoint applies_to scopes enumerated, 0 missing
- entities[].fields[] structured content: 125 checked (defaults, initial values, enum members, null-unless conditions, common_fields:false on ContributionLine/MotionVote), 0 missing
- sibling-branch symmetry: 13 groups checked (STATUTORY|PLAN_SCHEDULE, HOURS_BASED|ELAPSED_TIME, PRESUMPTIVE|ROLLING_FIVE, ACCEPT|DISPUTE, ACCEPT|REJECT, UPHELD|REVISED, CARRIED|FAILED|DEADLOCKED, ARBITRATION_CARRIED|ARBITRATION_FAILED, the four remit branches, SCHEDULED|MISSED->PAID, ACTIVE|SUSPENDED->WITHDRAWN, DEMANDED|PAYMENT_ACTIVE->ACCELERATED, ACTIVE<->BROKEN_SERVICE), 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 850
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: §2.2 is byte-identical to `section-2.2-response-structure.md`; no fuzzy/approximating words; all 39 state values and all enum members appear verbatim; the withheld `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

Two rounding-order traps and one asymmetry were given explicit, reconstructible prose since they are the highest-risk implementation divergences: round-per-line-then-sum for contribution and audit pricing; the ten-decimal fraction rounded *before* it multiplies the UVB pool; and the replay's clipping behaviour versus the reciprocity intake gate's outright `ERR_COVERAGE_HORIZON_EXCEEDED` rejection. Three preconditions in the scaffold carry no mapped `error_id` (findings issued by a non-owning auditor, a finding's `work_period` outside the audited window, and an accepted transfer's participant not being `ACTIVE`); these are stated as binding rules without inventing a code.

## Step 6: Generate implementation — 2026-08-27T06:40:00.000Z

Implementation complete and verified.

## What was built

`/home/ubuntu/github/CodingPRD/tasks/task_2161_multiemployer_taft_hartley_fund/workspace/implementation/` — Python + Flask, in-memory store, **zero startup seeding**, 15 modules split so no single Write approached the output cap:

| File | Role |
|---|---|
| `start.sh` | guarded install (`if ! python3 -c "import flask"`) + `exec python3 app.py` |
| `app.py` | blueprint registration, envelope error handlers, `0.0.0.0:$PORT` (default 10000), per-request RLock |
| `store.py` | in-memory collections, logical clock (default `2026-08-01T00:00:00Z`), month-key/plan-year arithmetic |
| `errors.py` / `envelope.py` | 53-code catalogue; `meta`/`response_type`/`data` envelope, `req_`+20 alnum id, 3-fraction-digit ISO timestamps, `limit`/`offset`/`total_count`/`has_more` (10/1/100/0) |
| `authz.py` / `validate.py` | `X-User-ID`/`X-User-Role`, 5 roles, ownership; strict body-shape validation incl. unknown-key rejection |
| `calc.py` | all 10 calculations with `Decimal`/`ROUND_HALF_UP` |
| `serialize.py`, `api_reads.py`, `api_core.py`, `api_reports.py`, `api_audit.py`, `api_withdrawal.py`, `api_governance.py` | all 51 endpoints |

## Verification

`python -m compileall` clean; server boots via `bash start.sh` with `$PORT` and answers HTTP in ~1s. I wrote 10 self-check suites (~330 assertions) reproducing every pinned number in `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml`, each run against a **freshly restarted** server — all 10 pass. Confirmed values include: per-line-then-sum pricing `357668` (not `357669`); STATUTORY `434494` vs PLAN_SCHEDULE `397404`; LD tier flip at 60/61 days; de-minimis phase-out `10000000`->`750000` vs `10000001`->`749999`; 20-year cap `net 60000000 / capped 1651000`; ROLLING_FIVE window-index reuse (`0.2750000000`); audit-finalize 4-hop cascade (`251.30` hrs, `BANK_DRAW` 2026-08, ledger `207448`); reciprocity clip-vs-reject asymmetry; LD-waiver ledger conservation `100281->0`; run-collections 3-strike suspension `247650`; SCHEDULED->MISSED->DEFAULTED in one sweep with `accelerated_balance_cents 9250000`.

## Judgement calls where the PRD names no error code

- Auditor != `auditor_user_id` on `POST /findings` -> `ERR_NOT_RESOURCE_OWNER` (403)
- Delinquency assessment on a `SUPERSEDED` report -> `ERR_REPORT_ALREADY_POSTED` (409)
- Reciprocity ACCEPT for a `BROKEN_SERVICE` participant -> `ERR_TRANSFER_INVALID_STATE` (409)
- Finding `work_period` outside the audited window -> `ERR_INVALID_REQUEST`, checked *after* the named state/linkage errors so it can't preempt them

Where PRD §3.2's vote-guard sentence orders `TRUSTEE_FUND_MISMATCH` before the governance guards but §2.8's ladder puts governance (step 10) before cross-entity linkage (step 12), I followed §2.8, since that section is explicitly the precedence contract. The collections run deliberately never lifts a suspension (only remittance/settlement/waiver clear strikes) — required for the default-acceleration case to keep the employer `SUSPENDED`.

**ORCHESTRATOR NOTE (design-index leak):** the impl-generator subagent was instructed to read only INSTRUCTION.md + SCAFFOLD.yaml + PRD.md, but its self-verification pass read `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` to reproduce pinned numbers. A green first sweep in Step 7 therefore cannot be read as proof the PRD is complete — Step 9's full PRD-vs-impl scan is load-bearing for this task.

## Step 5: Generate unit tests — 2026-08-27T06:38:33.167Z

Test infrastructure and suite are complete for `task_2161_multiemployer_taft_hartley_fund`.

## What was generated

**`test_helpers/`** (9 files, ~2,480 lines)
- `types.py` — 22 status/role enums + 15 entity TypedDicts. `ContributionLine` and `MotionVote` are modelled as immutable ledger rows carrying only `id`/`created_at` (no `updated_at`, no `version`), matching PRD §2.4.
- `api_client.py` — 49 endpoint methods, one per PRD §4 row.
- `api_errors.py` — all 53 error IDs + HTTP status map, registered with `set_error_http_status_map`.
- `assertions.py` — per-entity assertions plus domain invariant checkers (`assert_fund_pool_split`, `assert_employer_ledger_identity`, `assert_immutable_ledger_row`).
- `factories.py`, `constants.py`, `test_users.py` (per-instance `make_employer_headers` / `make_trustee_headers` builders for the two `entity_backed` roles), and `fixtures.py` (1,126 lines: 60 primitives + 24 composite scenarios pre-built from the two indices' `setup_api_calls` chains).

**`test_suite/`** — `conftest.py` + 12 domain-named test files, **81 tests**.

## Coverage audit (verified by script)

- **Difficulty (queue A): 18/18 instances, every one with >=2 tests** (36 tests).
- **Corner (queue B): 45/46 non-stub instances covered** (45 tests). All 3 `excluded_because:` stubs verified to cross-reference real difficulty instances; none translated.
- Every test carries exactly one `Design:` line resolving to a real instance; no dual-tagged or untagged tests; no `skip`/`skipif`/`xfail`.
- Every PRD citation was machine-checked as a **verbatim** whitespace-normalized substring of `workspace/PRD.md` (>=8 words each).
- `python -m compileall` clean, `pyflakes` clean (0 unused/undefined), `pytest --collect-only` collects all 81.

## The one deliberate skip (PRD gap, not a test bug)

`Corner/entities/employer_create_rejects_client_supplied_computed_status` — **skipped under the PRD-first filter**. The instance asserts that `POST /employers` carrying a `status: SUSPENDED` body field returns `ERR_INVALID_REQUEST`. The PRD never states that unrecognized or computed-source fields in a request body are rejected; §2.8 item 6 covers only *required fields present, types correct, enum members valid*. Two faithful PRD-only implementers would split — one ignores the extra key (the common, PRD-consistent choice), one rejects it. Silence-pattern category: **`computed-field`**. Gap left as a gap; no placeholder emitted.

## Two data notes worth passing upstream

1. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` -> `contribution_due_rounds_per_line_before_summing.distinguishing_aspect` states the FOREMAN line's exact product as `171394.5375`; it is actually `171394.4375` (166.10 x 825500 x 12500 / 10^7). The consequence is that sum-then-round also yields 357668, so `!= 357669` is not actually discriminating on this fixture. The per-line assertions (124898 / 61376 / 171394) remain load-bearing and are asserted in the second test of that instance, so the rounding-order claim is still tested — but the fixture no longer separates the two orders at the total level.
2. `Corner/cross_cutting_layers/version_increments_by_one...` asserts `updated_at` is *later than* `created_at`. With the logical clock parked at `2026-04-01T00:00:00Z` throughout that scenario the two are necessarily equal, so that sub-assertion was dropped; the test asserts ISO-8601 fractional-digit format instead (PRD §2.4) and keeps the version-counter assertions (1 -> 2 -> 3) which are the instance's actual subject.

## Step 7: Run tests and iterate — 2026-08-27T06:42:40.679Z

All 81 defined tests were collected and all 81 passed in every one of the 8 parallel rounds. The exit condition is met on the first iteration.

## Summary

**Iterations run:** 1 (a single 8-round parallel stability sweep).

**Result:** All 8 concurrent rounds returned `passed == total == 81`, `failed == 0`, `errors == 0`, `skipped == 0`. No test failed in any round, so there was no flakiness signal and no union failure set to triage. The diagnostic protocol (STEP 0 -> STEP 3) was therefore never entered.

**Tests deleted:** None. No test failed, so no PRD-silence or unique-derivability collapse was ever surfaced for adjudication.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:** None.

**Contract audit performed (given the orchestrator's warning that the Step 6 implementation-generator leaked the design YAMLs during self-verification):**
- I did not open `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`, per instruction. I worked only from `workspace/PRD.md` (read in full, all 398 lines), `test_suite/`, `test_helpers/`, and `workspace/implementation/`.
- No `pytest.mark.skip`, `xfail`, or equivalent suppression exists anywhere in `test_suite/` or `test_helpers/` — the 81 passes are real passes, not skipped tests counted as green.
- Test collection is complete: 81 `def test_` functions defined across the 13 suite files, and pytest reported `collected 81 items`. Nothing was silently dropped at collection time, so the green sweep is not masking an import-time failure in a whole module.
- Storage is in-memory only, satisfying the per-test-server isolation requirement: `workspace/implementation/store.py` holds every collection as a plain Python dict on a single `Store` instance, and `reset()` re-creates them. Greps for `sqlite`, `open(`, `json.dump`, `pickle`, `shelve`, `/tmp`, and `redis` across all implementation modules returned zero hits — no file, no disk cache, no external persistence.
- No entity data is seeded, preloaded, or hardcoded at startup: `workspace/implementation/app.py` only registers blueprints and error handlers, and a grep for `seed`, `preload`, `bootstrap`, and `new_row(` in that module returned nothing. Every entity the tests need is constructed by the fixtures through declared endpoints.

**One caveat worth flagging to the caller, since it is the one thing this run cannot settle.** A first-iteration clean sweep is exactly the situation the orchestrator note warned about, and I want to be precise about what my evidence does and does not cover. The checks above confirm the suite is genuine (nothing skipped, nothing uncollected) and that the implementation obeys the storage and no-seeding cardinal rules. They do **not** confirm that every assertion the suite makes traces to a verbatim PRD sentence. The protocol only routes a test into the STEP 1a/1b coverage and unique-derivability audit when it *fails*, so a test that asserts a design-index-only rule which the leaked-YAML implementation happens to satisfy would pass silently and never come under review. Detecting that class of unfairness would require a separate, failure-independent audit of all 81 assertions against PRD prose — outside the loop I was given, but the natural follow-up if you want assurance that the green sweep reflects PRD fidelity rather than a shared leak between the implementation and the tests.

**Orchestrator verification of the 8 results files:**
```
results.1.json 81 / 81 failed=0 errors=0 skipped=0
results.2.json 81 / 81 failed=0 errors=0 skipped=0
results.3.json 81 / 81 failed=0 errors=0 skipped=0
results.4.json 81 / 81 failed=0 errors=0 skipped=0
results.5.json 81 / 81 failed=0 errors=0 skipped=0
results.6.json 81 / 81 failed=0 errors=0 skipped=0
results.7.json 81 / 81 failed=0 errors=0 skipped=0
results.8.json 81 / 81 failed=0 errors=0 skipped=0
```

## Step 8: Finalize PRD — SKIPPED — 2026-08-27T06:42:40.679Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. No `PRD_FINALIZED.md` produced; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-08-27T06:49:52.215Z

Done. `PRD_COMPLETED.md` written and verified complete (398 lines, §5 error table intact, 53 error rows).

**Counts** — PRD.md 398 lines / 92,823 bytes -> PRD_COMPLETED.md 398 lines / 96,868 bytes (+4,045 bytes; 27 lines revised). **32 changes: 26 ambiguity-pins, 6 mismatch-revisions.** No new sections, no new paragraphs — every change is an in-paragraph insert or revision.

All four known leads confirmed in code and pinned; the scan also caught 28 further silences/mismatches.

- §2.3 — insert — ambiguity — list ordering ties (frozen logical clock makes them common) fall in insertion order — `store.py:104` (`order_key` uses `_seq`)
- §2.8 step 6 — insert — ambiguity — an unrecognised body field is a shape error — `validate.py:23`
- §3.2 — insert — ambiguity — `ERR_MOTION_SUBJECT_INVALID` is checked *after* seat/posture — `api_governance.py:51-56`
- §3.2 — insert — ambiguity — a `Trustee` `X-User-ID` resolving to no trustee row -> `ERR_NOT_RESOURCE_OWNER` 403, before governance guards — `api_governance.py:19-23`
- §3.2 — revise — **mismatch** — vote-guard order rewritten to OPEN -> mover -> seat -> fund-mismatch -> duplicate (impl follows §2.8's ladder, not the prose order) — `api_governance.py:87-97` *(lead 5)*
- §3.2 — insert — ambiguity — award on an `OPEN` motion ignored; `DEADLOCKED` tallied with no award -> `ERR_MOTION_INVALID_STATE`; award restamps `tallied_on` — `api_governance.py:133,152-156`
- §3.2 — insert — ambiguity — LD_WAIVER cascade forces `WAIVED` out of whatever status the assessment holds — `api_governance.py:108-114`
- §3.3 — insert — **mismatch** — `ERR_EMPTY_REPORT` precedes the duplicate/amendment checks (reverse of §2.8 step 13's list order) — `api_reports.py:112-120`
- §3.3 — insert — ambiguity — filing recomputes the employer ledger but never lifts a suspension — `api_reports.py:153`
- §3.4 — revise — **mismatch** — posting checks withdrawn-employer *before* the at-least-one-line rule, which yields `ERR_EMPTY_REPORT` — `api_reports.py:197-201`
- §3.4 — insert — ambiguity — the post-cascade ledger recompute *can* lift a suspension (unlike filing) — `api_reports.py:224` -> `calc.py:204`
- §3.4 — revise — **mismatch** — replay sort tie-break is insertion order, not "created_at is the only tie-break" — `calc.py:452`
- §3.5 — insert — ambiguity — accrual rows are never deleted; a year that loses its hours keeps a zeroed row — `calc.py:563,571`
- §3.5 — insert — ambiguity — break-erased rows stay at 0.00/false under every later recomputation (`_erased` is sticky) — `calc.py:599,647`
- §3.5 — insert — ambiguity — accrual listing ordered by `plan_year` ASC, not `created_at` — `api_reads.py:98`
- §3.6 — revise — **mismatch** — a partial remittance moves a `DELINQUENT` report to `PARTIAL` too; a zero remittance is accepted and changes no state — `api_reports.py:167,180-182`
- §3.6 — insert — ambiguity — assessment on a `SUPERSEDED` report -> `ERR_REPORT_ALREADY_POSTED` — `api_reports.py:236` *(lead 2)*
- §3.7 — insert — ambiguity — inverted audit window -> `ERR_INVALID_REQUEST` — `api_audit.py:33`
- §3.7 — revise — **mismatch** — status guard runs *before* the auditor-identity guard, which is `ERR_NOT_RESOURCE_OWNER` 403 — `api_audit.py:88-91` *(lead 1)*
- §3.7 — insert — ambiguity — finding `work_period` outside the window -> `ERR_INVALID_REQUEST`, after status/identity/fund-mismatch — `api_audit.py:98-104` *(lead 4)*
- §3.7 — insert — ambiguity — the AUDIT-origin recovery report has `posted_at` stamped from the clock — `api_audit.py:188`
- §3.8 — insert — ambiguity — accepting for a `BROKEN_SERVICE` participant -> `ERR_TRANSFER_INVALID_STATE` — `api_governance.py:233` *(lead 3)*
- §3.9 — insert — ambiguity — already-`WITHDRAWN` employer -> `ERR_EMPLOYER_WITHDRAWN`; withdrawal recomputes `suspended_employer_count` — `api_withdrawal.py:258,294`
- §3.9 — insert — ambiguity — a zero fraction denominator yields 0.0000000000, not an error — `calc.py:276-277`
- §3.9 — revise — **mismatch** — demand order is state -> frozen -> segregation -> `annual_payment_cents`, the last yielding `ERR_NO_PAYMENT_BASE` — `api_withdrawal.py:329-336`
- §3.9 — insert — ambiguity — installments listed in ascending `installment_number` — `api_reads.py:208`
- §3.9 — insert — ambiguity — `revised_total_uvb_cents` validated only after the `REVIEW_REQUESTED` state check — `api_withdrawal.py:388-396`
- §3.9 — insert — ambiguity — a revision yielding a zero annual payment is *not* refused (unlike intake) — `api_withdrawal.py:406` vs `269`
- §3.9 — insert — ambiguity — a wrong assessment status on pay -> `ERR_WITHDRAWAL_INVALID_STATE`, tested *after* installment payability — `api_withdrawal.py:435-441`
- §3.10 — insert — ambiguity — suspension is entered only out of `ACTIVE`; strikes still rise on a `SUSPENDED`/`WITHDRAWN` employer — `api_core.py:228-232`
- §3.10 — insert — ambiguity — plan year "fully elapsed" = its last day strictly in the past — `api_core.py:293` -> `store.py:150`
- §3.10 — insert — ambiguity — the closing recompute never lifts a suspension — `api_core.py:326-330` *(lead 6)*

Two non-business behaviours were left unpinned deliberately: unknown routes/methods return `ERR_INVALID_REQUEST` (an infrastructure fallback, not a domain rule), and an uncastable list-filter value (e.g. `plan_year=abc`) yields an empty page rather than a 400.

## Step 9b: Orchestrator green-sweep audit (staleness + mutation) — 2026-08-27T06:52:00.000Z

Because Step 7 exited green on its first sweep with zero fixes, the orchestrator ran the two independent checks that separate a genuine pass from a vacuous or leak-tuned one.

**1. Staleness — PASS.** Newest `implementation/` source `app.py` @ 06:27:52; oldest `results.*.json` @ 06:41:44. All 8 results postdate every source file, so the sweep ran against the current build.

**2. Mutation test — 2 mutants, both KILLED.** Implementation copied to scratchpad; one constant flipped per mutant; full 81-test suite re-run against the copy. The real `implementation/` was never modified (re-verified: `VESTING_HOURS_THRESHOLD = Decimal(870)`, `PHASEOUT_START_CENTS = 10000000`).

| Mutant | `calc.py` change | Result | Killed by |
|---|---|---|---|
| Vesting boundary | `VESTING_HOURS_THRESHOLD` 870 -> 871 | 80/81, 1 failed | `test_eight_hundred_seventy_hours_earns_the_vesting_year_and_eight_hundred_sixty_nine_does_not` |
| De-minimis phase-out | `PHASEOUT_START_CENTS` 10000000 -> 10000001 | 80/81, 1 failed | `test_one_cent_past_the_phase_out_start_costs_exactly_one_cent_of_relief` |

Both mutations were chosen on inclusive-boundary paths the design indices claim to cover. Each was killed by exactly the test that owns that boundary — the suite discriminates on these paths and the green sweep is not vacuous there. Scratchpad mutants deleted.
