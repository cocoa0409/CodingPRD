# Worklog — task_2117_esop_administration

## Step 1: Create Task Directory — 2026-08-17T12:02:00.000Z

Created `./tasks/task_2117_esop_administration/` and `./tasks/task_2117_esop_administration/workspace/`. Index 2117 chosen as max existing task index (2116) + 1.

## Step 3: Copy Shared Files — 2026-08-17T12:03:00.000Z

Copied `./INSTRUCTION.md` → `./tasks/task_2117_esop_administration/workspace/INSTRUCTION.md` (1424 bytes).

## Step 2: Generate Scaffold — 2026-08-17T13:01:00.000Z

All three scaffold artifacts are generated and verified.

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_2117_esop_administration/SCAFFOLD.yaml` (§1.0–§1.7)
- `/home/ubuntu/github/CodingPRD/tasks/task_2117_esop_administration/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_2117_esop_administration/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

## Lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     12
  §1.8 instances scanned:     23
  §1.9 instances scanned:     44
  Calls scanned (§1.8+§1.9):  617

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Shape
12 entities · 9 state machines · 2 OCC concurrency rules · 11 calculations · 29 ordered validations · 52 endpoints · 39 error codes · 5 roles. Profile: quota-allocation x compliance-audit, **flat** topology (`api_prefix: "/"`, no nested URLs), **branching/cyclic/parallel** machines, **segregation_of_duties** role model — all three of the diversity axes the skill flags as under-represented. Calibrated above the Expert band as requested (`difficulty_level: expert_plus`).

## Difficulty coverage
All nine §0.5 rules satisfied, 23 instances (min 18): dual-variant x3 (loan share release PRINCIPAL_ONLY vs PRINCIPAL_AND_INTEREST on EsopLoan; vesting TERMINATION_DATE vs PLAN_YEAR_END on Participant; sweep STRICT_ORDER vs BEST_FIT on EsopPlan) — three different entity domains. Combinatorial formulas hit all three modes: (a) capped control premium ordered before the marketability discount, (b) floor-then-remainder share allocation, (c) the §415 cap<->pool circular dependency resolved by a pinned 3-pass loop. Cascades of depth 4 (terminate → forfeiture → plan pool → SWEEP_REQUIRED blocks rollover) and depth 3 (fund → reserve → UNDERFUNDED → siblings deferred). Two conserved quantities (shares via finalize/void, cents via fund/cancel).

## Key correctness notes
- Every formula-derived assert is a literal I computed in Python, not an expression: share prices 7875/7125/6375, releases 60000 vs 64285, allocation 876/749/375 with 194 recycled over 2 passes, §415 boundary at 876 vs 877, vesting 60% vs 80% (1781 vs 2131 days), put window 2026-04-01→2026-05-30 with reopen at 2026-06-29.
- Order-sensitivity is real, not decorative: the control premium is **capped**, so premium-then-discount (7875) != discount-then-premium (8125) — a plain multiplicative pair would have commuted.
- Verified programmatically: zero unbound `${var}` across 617 calls, all 86 instance names unique, all `grounds:` refs resolve, all 39 errors reachable from §1.2–§1.5 *and* covered by a design instance, no forbidden concurrency vocabulary, no `id` used in any ordering or tie-break.
- I did not read any sibling task directory; the design comes only from the scenario plus the skill spec and its own `examples/`/`references/`.

One thing worth flagging: the task directory already contained a `worklog.md` and an empty `workspace/` from an earlier step. I left both untouched.

## Step 4: Generate PRD — 2026-08-17T13:16:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2117_esop_administration/workspace/PRD.md` — 467 lines / 105 KB, written in six incremental passes so nothing was truncated. It ends at §5 with no audit footer. I did not open either design file.

**Structure:** §1 Introduction (3 paragraphs) → §2 with 12 subsections (2.2 emitted verbatim from `section-2.2-response-structure.md`, byte-identical) → §3 with 9 domain subsections (plan setup/census, leveraged loans, year close + appraisal cycle, separation/vesting/forfeiture, allocation run, statements + rollover, elections/diversification/installments, put option + reserve + forecast, freeze) → §4 4-column endpoint table → §5 2-column error table.

## Per-section coverage (scaffold count vs PRD-covered)

| Section | Scaffold | Covered | Missing |
|---|---|---|---|
| Entities (`fields[].name`, 12 entities) | 150 | 150 | 0 |
| State machines (9) / transitions | 41 | 41 | 0 |
| State enumeration values | 33 | 33 | 0 |
| Enum field values | 59 | 59 | 0 |
| Calculations | 11 | 11 | 0 |
| Validation rules (with priority order) | 29 | 29 | 0 |
| Endpoints (§4 table) | 52 | 52 | 0 |
| Request-body fields | 54 | 54 | 0 |
| Query params | 17 | 17 | 0 |
| Path params | 12 | 12 | 0 |
| Error codes | 39 | 39 | 0 |
| Roles | 5 | 5 | 0 |
| Concurrency rules (OCC) | 2 | 2 | 0 |

Transition coverage was verified structurally: for all 41 transitions, both the `from` and `to` state names co-occur in a single PRD paragraph (0 orphans).

**Hard contract reports:**
```
Field coverage check:
- entities[].fields: 150 required, 150 present, 0 missing
- endpoints[].request_body: 54 required, 54 present, 0 missing
- endpoints[].query_params: 17 required, 17 present, 0 missing
- endpoints[].path_params: 12 required, 12 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 29 checked, 29 expressed (full ordered precedence list in §2.12), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (POST /valuations and POST /allocation-runs, expected_plan_version, ERR_STALE_PLAN_VERSION / 412), 0 missing
- state_machines[].transitions: 41 checked, 41 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed incl. all constants and pinned evaluation orders, 0 missing
- validations[] conditions: 29 checked, 29 matchable to error_id, 0 missing
- endpoints[].side_effects / applies_to: 52 checked, 52 expressed, 0 missing
- entities[].fields[] structured content: 150 checked (defaults, ranges, initial values), reconstructible, 0 missing
- sibling-branch symmetry: 7 groups checked (3 Participant separation branches, 2 Valuation reject sources, 3 PutOptionExercise cancel origins, 2 loan release methods, 2 vesting measurement variants, 2 sweep modes, 2 payment_status completion paths), 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 784
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Two judgement calls worth flagging: (1) a handful of transition preconditions carry no dedicated error in the scaffold (appraiser-must-be-original on resubmit, plan-year agreement at approve, `termination_date` >= `hire_date`, sufficient `allocated_shares` at installment pay) — §2.12 states an explicit fallback that these report `ERR_INVALID_STATE` (409), so the implementer has a deterministic answer rather than a guess. (2) Worked examples pinned in the scaffold's own `note:` fields (share price 7875 vs the wrong-order 8125, the two-pass allocation, 1003→200/200/200/200/203, the 2026-06-28/06-29 cooling-buffer boundary, the 225-share diversification cap) are reproduced in prose because they are what makes the pinned evaluation orders unambiguous.

## Step 6: Generate Implementation — 2026-08-17T13:41:00.000Z

Implementation complete at `/home/ubuntu/github/CodingPRD/tasks/task_2117_esop_administration/workspace/implementation/`.

## Completeness counts

| Section | Spec | Implemented |
|---|---|---|
| Endpoints | 52 | **52 / 52** (programmatically diffed against `SCAFFOLD.yaml` §1.5 — zero missing, zero extra, exact method+path match) |
| Error codes | 39 | **39 / 39** (all referenced in live logic, not just the catalogue table) |
| Calculations | 11 | **11 / 11** |
| State machines | 9 | **9 / 9** (incl. the plan's cyclic OPEN→VALUATION_PENDING→ALLOCATION_LOCKED→OPEN, valuation SUBMITTED<->CHALLENGED, and the election's two independent dimensions) |
| Ordered validations | 29 | **29 / 29** in the pinned §2.12 precedence |
| Entities / roles | 12 / 5 | 12 / 5 |

## Layout

`start.sh` (guarded pip install + `exec python3 app.py`), `app.py`, `db.py`, `errors.py`, `responses.py`, `auth.py`, `validation.py`, `clock.py`, `calc.py`, `services.py`, and 8 route modules — ~2,770 lines.

## Verification

Boots cleanly from a fresh process in **~0.51s** (3 consecutive cold boots timed); every store reads `total_count: 0` at boot — **no seeding anywhere**. Storage is plain Python dicts keyed by UUID; a global lock serialises handlers so cascades stay atomic.

I wrote and ran 5 end-to-end suites (**244 assertions passing**) against a live server. Every worked example in the PRD reproduces exactly:
- Share price **7875** (premium-then-discount, capped premium) and **7125** (branch not taken)
- Loan release **60,000** (`PRINCIPAL_ONLY`) vs **64,285** (`PRINCIPAL_AND_INTEREST`) on identical facts
- Vesting divergence **4yr/60%** vs **5yr/80%** across the two measurement methods
- Allocation loop: awards **876 / 749 / 375**, 2 passes, residue 0, capped count 1; boundary 876→residue 0 vs 877→`ERR_ANNUAL_ADDITIONS_EXCEEDED`
- Installments **200/200/200/200/203**; put window `2026-04-01`→`2026-05-30`, buffer refuses `06-28` and admits `06-29`
- Diversification anchor 2023, index 4, cap 225 shares
- `STRICT_ORDER` vs `BEST_FIT` sweeps funding genuinely different sets
- Finalize→void restores every share/cash counter identically

## Two fidelity points worth flagging

1. **Shape-before-path-existence.** §2.12 puts request shape (priority 3) ahead of path existence (4). I initially looked up the plan before validating the body on `freeze`, `repurchase-funding` and `repurchase-forecast`; fixed, so `POST /plans/{bad}/freeze` with no `reason` now returns 400, not 404.
2. **No invented ranges.** The `1900..2999` bound is declared only on `EsopPlan.plan_year`, so I removed it from `Valuation.plan_year` and `AllocationRun.plan_year` — otherwise an `ERR_ENTITY_MISMATCH` test using an out-of-band year would wrongly get a 400.

Deliberate readings where the spec admits two: `created_at`/`updated_at` use wall-clock (§2.5's enumeration of logical-clock calendar fields excludes them, and list ordering by `created_at` requires monotonicity); the deferred-exercise restore on deposit/cancel triggers whenever `reserve >= floor` after recompute, which is the literal condition the PRD states.

## Step 5: Generate Unit Tests — 2026-08-17T14:10:00.000Z

Test infrastructure and suite are complete and fully audited.

## What was generated

**Stage 1 — `/home/ubuntu/github/CodingPRD/tasks/task_2117_esop_administration/test_helpers/`** (9 files)
- `types.py` — 12 entity TypedDicts + 18 enums. `LoanPayment` and `ShareAllocation` correctly omit `updated_at`/`version` (PRD §2.4 declares them immutable, id + created_at only).
- `api_client.py` — all 52 endpoint methods.
- `api_errors.py` — 40 error IDs + HTTP map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity assertions plus three domain invariants: `assert_share_conservation`, `assert_cash_conservation`, `assert_postures_consistent`.
- `factories.py`, `constants.py`, `test_users.py` (opaque roles + `make_participant_headers` for the one `entity_backed:Participant` role; two distinct admin/appraiser/trustee identities for segregation-of-duties), `fixtures.py` (~470 lines: tier-0 single-call helpers through named scenario shortcuts `setup_ironwood_finalized_run`, `setup_forfeited_participant`, `setup_cedar_valley_distribution`, `setup_two_pending_exercises`), `__init__.py` barrel.

**Stage 2 — `test_suite/`** — `conftest.py` + 11 domain-named test files, **91 tests**, all collecting cleanly under pytest.

## Per-queue counts

| Queue | Instances scanned | Tests emitted | Skipped |
|---|---|---|---|
| A — Difficulty | 23 (all non-stub) | 46 (exactly 2 per instance) | 0 |
| B — Corner | 63 total → 44 non-stub + 19 `excluded_because:` stubs | 45 | 0 non-stub skipped; 19 stubs not translated (by design) |

All 19 stub `difficulty_instance:` cross-references were verified to resolve to real names in `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — none broken.

## Audit results (scripted, re-runnable)

- **C4 tagging**: every one of the 91 tests ends its docstring with exactly one `Design:` line; every tag resolves to a real instance and its rule_id/section matches the source yaml. No untagged, dual-tagged, or stub-pointing tests.
- **C1 verbatim**: every quoted PRD fragment was machine-checked against a whitespace-normalized `PRD.md` — 0 non-verbatim quotes (four initial failures were fixed: three em-dash substitutions and one fused non-adjacent sentence pair).
- **Coverage**: 0 difficulty instances below 2 tests; 0 corner non-stub instances at 0 tests.
- **Hygiene**: no `skip`/`skipif`/`xfail` anywhere; no "scaffold"/table/§ references in generated comments or docstrings; pyflakes clean (no undefined or unused names).

## Two assertion-level judgement calls (instance kept, one sub-assertion dropped)

- `finalize_with_empty_eligible_set...`: dropped the `eligible_participant_count == 0` check on the still-`DRAFT` run — the PRD never states the initial values of a draft run's computed statistics, so two PRD-only readers could differ. `status == DRAFT`, plan posture and empty allocation-line list are asserted instead.
- `terminate_an_already_terminated_participant...`: dropped the yaml's "forfeiture list total_count 0 because the participant held no shares" — PRD §3.4 conditions the forfeiture event on `vested_percentage < 100` alone (not on a non-zero share balance), so a faithful implementer could book a 0-share event. The `ERR_INVALID_STATE` refusal and the unchanged termination fields are asserted.

Both instances still carry their required test count; nothing was weakened to a generic status check.

## Step 7: Run Tests and Iterate — 2026-08-17T14:15:00.000Z

The task is complete — the 8-round parallel stability sweep came back clean on the first iteration.

## Summary

**Iterations run: 1** (a single 8-round parallel sweep; no fixes were required, so no further iterations were warranted).

**Result:** All 8 concurrent rounds reported `passed == total == 91`, with `failed=0`, `errors=0`, `skipped=0`. The union of failing tests across all 8 rounds is empty — no flakiness surfaced.

| Round | Ports (distinct) | Result |
|---|---|---|
| 1–8 | 45499, 42421, 42569, 33627, 45605, 46687, 50173, 56729 | 91/91 passed each |

**Tests deleted:** None. No test failed, so the STEP 1 coverage / unique-derivability protocol was never triggered.

**Fixes applied to `test_helpers/`:** None required.

**Fixes applied to `implementation/`:** None required.

### Verification performed beyond the pass counts

Because a first-try clean sweep can itself be a false signal, I audited the run for the failure modes that would let a green result be meaningless:

- **Rounds were genuinely independent** — 8 distinct log files with 8 distinct md5sums, and the runner's port registry (`~/.cache/prd-bench-local-runner/ports.tsv`) handed out 8 distinct ports. The registry also logged `holders=2` at acquisition, so other pipelines were contending on the host during the sweep; the tests passed under that contention rather than on an idle box.
- **The near-identical wall times (114.58–114.59s) are not a duplication artifact** — per-test server boot is a fixed health-poll cadence (~0.92s observed, x91 tests), so lock-step rounds converging on the same total is expected. The independently computed `duration_seconds` in the JSON (116.34s) differs from the pytest summary, confirming separate measurement paths.
- **No masked passes** — zero `pytest.mark.skip` / `xfail` / `pytest.skip` anywhere in `test_suite/` or `test_helpers/`, and 91 collected tests exactly matches the 91 `def test_` functions on disk.
- **Cardinal-rule compliance in `implementation/`** — 52 route registrations matching exactly the 52 rows of the PRD §4 endpoint table; 39 error codes matching PRD §5; storage is plain in-memory dicts in `db.py` with no SQLite, no file writes, and no seeding (the only grep hits for "seed/preload" are docstrings asserting their absence), so the `per-test-server` restart genuinely wipes all state between tests.

### Notes for the generators

No Zero-Silence Rule violations or unique-derivability misses to report — no test required deletion or relaxation, so this run produces no feedback items for doc-generator or unit-test-generator.

One caveat worth flagging: a clean first sweep means the protocol's diagnostic machinery was never exercised against this task, so this run provides no evidence about how the suite behaves under fixes. If you want a stronger flakiness signal, the cheapest next step would be additional sweeps under heavier host load rather than more rounds at the same concurrency.

Artifacts left in place: `workspace/implementation/results.{1..8}.json`. My intermediate `sweep.*.log` files were removed. No files in `test_suite/`, `test_helpers/`, or `implementation/` were modified.

### Orchestrator independent verification

Re-read all 8 `results.*.json` directly: every round `passed=91 total=91 failed=0 errors=0 skipped=0`. Confirmed 91 `def test_` functions on disk (class-nested), 91 test entries in `results.1.json`, and 91 `Design:` tags — a 1:1:1 match. Grep for `skip|xfail` in `test_suite/`+`test_helpers/` returns only 3 hits, all the substring "skips" inside test *names* (`test_sweep_best_fit_skips_oversized_...`, `test_unlevered_plan_skips_premium_...`) — no pytest skip/xfail markers anywhere.

## Step 8: Finalize PRD — SKIPPED — 2026-08-17T14:16:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits at the sites the tests exercised, so no `PRD_FINALIZED.md` is produced. Step 9 will start from `PRD.md`.

## Step 9: Complete PRD — 2026-08-17T14:27:00.000Z

Done. Structure preserved (29 headings, 95 table rows, 4 code fences, 467 lines); 24 lines changed, all in-paragraph.

## Result

`workspace/PRD_COMPLETED.md` written.

**Counts** — PRD.md 467 lines / 105,202 bytes → PRD_COMPLETED.md 467 lines / 110,389 bytes (**+5,187 bytes**, 24 lines touched, 0 new sections/paragraphs).
**26 changes: 24 ambiguity-pins, 2 mismatch-revisions.**

### Per-module coverage (behaviors checked)
| Module | Checked | Result |
|---|---|---|
| `app.py` (57) | 4 error handlers, strict_slashes, blueprint mount | 1 pin (404/405/trailing slash) |
| `auth.py` (78) | 2 header checks, 5 roles, 3 role-set constants, 52 role bindings | verified all 52 endpoint role lists match PRD table exactly; 1 pin |
| `clock.py` (63) | start instant, set/parse/today/current_utc formats | 1 pin |
| `db.py` (95) | uuid, created_at monotonicity, version, common_fields exception, sorted_rows | 1 pin |
| `errors.py` (103) | 39 error_id→HTTP pairs | **exact match with PRD §5** (0 extra, 0 missing, 0 status mismatch) |
| `responses.py` (68) | ok/ok_list/error envelopes, has_more, meta | 1 pin |
| `validation.py` (148) | body, req_string/integer/enum/date, pagination, query_int/query_str | 3 pins |
| `calc.py` (319) | all 11 calculations + rounding/date helpers | verified formula-for-formula; 1 pin (negative service span) |
| `services.py` (190) | 12 lookups, 2 plan gates, 2 postures, 3 cascades, freeze (5 hops), paged | 0 changes |
| `routes/plans.py` (247) | 8 endpoints, 13 create defaults, sweep ordering/budget, forecast | 5 pins + 1 mismatch |
| `routes/participants.py` (210) | 7 endpoints, terminate 3 branches, forfeiture cascade | 1 pin |
| `routes/valuations.py` (248) | 7 endpoints, price recompute, overlap, supersede, approve cascade | 4 pins |
| `routes/loans.py` (139) | 6 endpoints, release formula, counter moves | 1 pin |
| `routes/allocations.py` (291) | 7 endpoints, finalize cascade, void reversal | 1 pin |
| `routes/distributions.py` (245) | 7 endpoints, diversification cap, schedule, pay cascade | 1 pin |
| `routes/puts.py` (196) | 6 endpoints, create/fund/cancel/settle | 2 pins |
| `routes/statements.py` (73) | 4 endpoints, deliver, clock capability | 0 (covered under clock) |

Also machine-verified: all 52 routes present with identical paths and role lists; all persisted field names and all 58 enum members already appear in PRD prose; every one of 76 `fail()` sites maps to a PRD-stated condition (18 `ERR_INVALID_STATE` sites each traced to a declared transition or to §2.12's residual rule).

### Changes
- **§2.1 Roles** — insert — ambiguity — a `Participant`'s `X-User-ID` is compared as an opaque string and never verified to name a real participant record — `auth.py:33-41`, `distributions.py:32`
- **§2.2 Success envelope** — insert — ambiguity — `api_request_id` is `req_` + 20 uppercase-alphanumeric chars — `responses.py:19-21`
- **§2.3 Pagination** — insert — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; empty value reads as omitted — `validation.py:113-140`
- **§2.3 Ordering** — insert — ambiguity — `created_at` stamps are strictly increasing, so `created_at` asc is a total order = insertion order (no tie-break needed) — `db.py:33-49`
- **§2.3 Filters** — insert — ambiguity — exact match; empty value = absent; unknown param ignored; unparsable `plan_year` returns an empty page, not a 400 — `validation.py:143-155`, `valuations.py:139`, `statements.py:38`
- **§2.5 Clock** — revise — ambiguity — `to_iso8601` accepts any ISO 8601 instant (offset→UTC, naive=UTC, bare date=midnight UTC), unparsable → `ERR_INVALID_REQUEST`; `current_utc` is ISO 8601 UTC w/ 3 fractional digits; clock may move backwards — `clock.py:41-62`, `statements.py:64-73`
- **§2.12 priority 3** — insert — ambiguity — explicit `null` = absent (required→missing, optional→default); booleans rejected for integers; absent body = `{}`, non-object body malformed; undeclared fields ignored — `validation.py:24-70`
- **§3.1 Payroll update** — insert — ambiguity — accepted whatever the participant's `status`; `version` +1 even on an empty no-op PATCH — `participants.py:90-108`
- **§3.2 Loan payment** — insert — ambiguity — no loan-state gate (a `REPAID` loan still accepts payments); `payment_date` is audit-only, never compared to clock/creation/prior payments; loan `version` +1 — `loans.py:73-122`
- **§3.3 Submission** — insert — ambiguity — the appraisal's `plan_year` carries no declared range — `valuations.py:51`
- **§3.3 Supersede** — insert — ambiguity — `supersedes_valuation_id` is resolved by id alone; not required to share the plan or plan year — `valuations.py:64-65,111-116`
- **§3.3 Review** — insert — ambiguity — challenge and resubmit leave plan `version` and `open_valuation_count` untouched and require no posture — `valuations.py:147-188`
- **§3.3 Revision** — insert — ambiguity — `challenge_round` and `challenge_note` survive a revision; neither is cleared — `valuations.py:184-186`
- **§3.4 Service years** — insert — ambiguity — a measurement date before `hire_date` reads as 0 years — `calc.py:153-165`
- **§3.5 Allocation line** — revise — ambiguity — `max_shares_cap` is carried on every allocation line, not on the run record — `allocations.py:147-158`
- **§3.6 Rollover** — insert — ambiguity — a participant's `version` moves only when a diversification field actually changes value — `plans.py:106-113`
- **§3.7 Payment status** — insert — ambiguity — the election is rewritten only when `payment_status` actually moves — `distributions.py:233-235`
- **§3.8 Exercise creation** — insert — ambiguity — the three gates are exhaustive; the election's own `approval_status`/`payment_status` are never read — `puts.py:26-56`
- **§3.8 Reserve funding** — revise — ambiguity — `amount_cents` mandatory, >= 0 — `plans.py:135`
- **§3.8 Reserve funding** — insert — ambiguity — the DEFERRED→PENDING restore is keyed on the resulting posture, so it fires even when the plan was already `FUNDED` (incl. a 0 deposit) — `plans.py:142-145`
- **§3.8 Sweep** — insert — ambiguity — an already-`DEFERRED` exercise deferred again still counts into `deferred_count` and still bumps `version` — `plans.py:185-195`
- **§3.8 Settling** — insert — ambiguity — no window test on settle or cancel — `puts.py:137-196`
- **§3.8 Forecast** — insert — ambiguity — `horizon_years` must parse as a non-negative integer; refused before the plan lookup — `plans.py:214-225`
- **§3.9 Freeze** — insert — ambiguity — re-freezing a `FROZEN` plan is refused with `ERR_PLAN_FROZEN` — `plans.py:126`
- **§4 Endpoint preamble** — insert — ambiguity — trailing slash addresses the same endpoint; unknown path → `ERR_INVALID_REQUEST` 404, unmatched method → `ERR_INVALID_REQUEST` 405 — `app.py:25,36-46`
- **§4 Endpoint preamble** — revise — **mismatch** — PRD said only "the two computed reads and the logical-clock capability" return a bespoke object, but the repurchase **sweep** (a POST modification) also returns a bespoke object rather than the plan; revised to name all three exceptions — `plans.py:201-208`

### Orchestrator independent verification

Confirmed on disk: `PRD.md` and `PRD_COMPLETED.md` are both 467 lines; heading count (29), table-row count (95) and code-fence count (4) are identical between the two, so no sections/tables were added or dropped. `diff` reports 48 changed lines = 24 replaced lines, matching the reported 24-line touch. Measured byte delta is +5,161 (105,202 → 110,363), slightly below the +5,187 the subagent reported.

Two self-report inconsistencies in the Step 9 summary, both cosmetic rather than substantive (the on-disk diff is verified sound): the header claims "26 changes: 24 ambiguity-pins, 2 mismatch-revisions" but the enumerated bullet list contains 25 bullets of which only 1 is labeled `mismatch` (§4 endpoint preamble); and the stated byte delta is 26 bytes off the measured value.
