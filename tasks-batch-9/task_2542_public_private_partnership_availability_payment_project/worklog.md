# Worklog — task_2542_public_private_partnership_availability_payment_project

## Step 1: Create task directory — 2026-09-03T08:40:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2542_public_private_partnership_availability_payment_project` and its `workspace/` subdirectory. Index 2542 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no index allocation was attempted (32 concurrent pipelines on this host would collide).

## Step 2: Generate Scaffold — 2026-09-03T10:41:00.000Z

Done. All three artifacts are written, self-consistent, and lint-clean.

## Files

| Path | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_2542_public_private_partnership_availability_payment_project/SCAFFOLD.yaml` | 3262 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2542_public_private_partnership_availability_payment_project/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2218 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2542_public_private_partnership_availability_payment_project/SCAFFOLD_CORNER_DESIGN.yaml` | 5528 |

## SCAFFOLD.yaml (§1.0–§1.7)
`difficulty_level: expert_plus`, archetypes ledger_reconciliation / compliance_audit, topology flat, state-machine shape cyclic, role model segregation_of_duties, consistency immediate. Layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers.

- **11 entities** (Concessionaire, Concession, DrawdownMilestone, ServicePeriod, PerformanceReport, DeductionEvent, DeductionDispute, ReliefClaim, LifecycleReserveTransaction `common_fields: false`, RefinancingEvent, EnforcementAction)
- **11 state-machine blocks** (ServicePeriod carries two independent axes; DeductionDispute cyclic bounded at 3 rounds; EnforcementAction branching; Concession cyclic through STEP_IN) + **3 concurrency rules**
- **20 calculations**, 4 of them dual-variant or conservation invariants; **24 validations** (priority ladder 1→76); **57 endpoints**; **40 errors**; **5 roles** with 4 segregation pairs on `X-User-ID`

## Design indices
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml — 24 instances** over 9 rule_id blocks: dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 4, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2.
- **SCAFFOLD_CORNER_DESIGN.yaml — 102 instances** (76 with full `test_recipe`, 26 stubs deferring to a named difficulty instance): entities 14, state_machines 18, calculations 14, validations 17, endpoints 6, errors 16, rbac 6, cross_cutting_complexity_layers 9, consistency_model 2.

## Verification
- `scaffold_lint.py` (absolute paths): **VERDICT: clean lint** — 1112 calls scanned across §1.8+§1.9, all conform to §1.5, all FKs reverse-reachable.
- Audits run and clean: no non-schema keys; every stub's `difficulty_instance` resolves by name; no duplicate instance names across the two indices; zero invalid `Entity.${id}.field` references; **all 57 endpoints and all 40 error codes are exercised** somewhere in §1.8 ∪ §1.9.
- Two consistency repairs made along the way: eight `calculations.<name>` grounds citations in the corner file pointed at non-existent calculation names (e.g. `liquidated_damages` → `liquidated_damages_late_commencement`, `deduction_cap_allocation` → `period_deduction_cap_allocation`) and were corrected; `ServicePeriod.availability_ratio` in SCAFFOLD.yaml said "6 decimal places" while its own worked fixture and both design indices use 4 dp — the entity description is now 4 dp.
- Pre-existing `worklog.md` and empty `workspace/` (created by the invoking pipeline at directory setup) were left untouched; no report files were written.

Orchestrator verification: `ls`/`wc -l` confirms SCAFFOLD.yaml (3262), SCAFFOLD_DIFFICULTY_DESIGN.yaml (2218), SCAFFOLD_CORNER_DESIGN.yaml (5528) all present in the task dir.

## Step 3: Copy Shared Files — 2026-09-03T10:41:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2542_public_private_partnership_availability_payment_project/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T10:58:00.000Z

PRD generation for task 2542 is complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2542_public_private_partnership_availability_payment_project/workspace/PRD.md`
**Final line count:** 425 lines (100,752 bytes). File ends at a complete section boundary — the last row of the §5 error table (`ERR_NO_REFINANCING_GAIN | 422`), not mid-sentence. Written incrementally via `cat >> … <<'PRDEOF'` heredocs throughout; no truncation.

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 Parties, Roles and Access Control; 2.2 API Response Structure (byte-identical to `section-2.2-response-structure.md`, verified by diff); 2.3 Pagination; 2.4 Resource Identity, Audit Stamps and the Append-Only Exception; 2.5 Money, Percentages and Rounding Discipline; 2.6 The Logical Clock, Calendar Days and Interval Conventions; 2.7 Optimistic Concurrency on the Parent Version; 2.8 Segregation of Duties; 2.9 Rejection Precedence; 2.10 Resource Addressing and Reverse Reachability; 2.11 Cascade Discipline and Immediate Consistency
- §3 Business Logic & Workflows — 3.1 Sponsor Registration to Financial Close; 3.2 Milestone Drawdown and the Construction Trigger; 3.3 Service Commencement, Late Delivery, Opening Payment Periods; 3.4 Self-Reported Performance and Verification; 3.5 Deduction Events, Dual Cap Allocation, Points Regime; 3.6 Disputing a Deduction (bounded referral cycle); 3.7 Relief, Compensation and Change-in-Law Claims; 3.8 Invoicing, Payment and Post-Payment Adjustment; 3.9 Lifecycle Reserve Ledger and Handback; 3.10 Refinancing and Gain Sharing; 3.11 Enforcement: Step-In, Cure, Escalation, Termination
- §4 Endpoint Definitions (intro + 57-row table: Method / Path / Description / Authorized Role(s))
- §5 Error Code Catalogue (40-row table)

**Coverage verification (scripted against SCAFFOLD.yaml, run twice)**
- Contract 1 — Field-Name Coverage: **PASS**. 149 required identifiers (all `entities[].fields[].name` + `common_fields`, all POST/PATCH body inputs, all GET query params, all path params); 0 missing from the backticked-token set.
- Contract 2 — Rule Coverage: **PASS**. All 57 endpoints appear in §4 and each is described in §3 prose with its preconditions, side effects and rejections; all 40 errors appear in §2/§3 prose (not merely in the §5 table); all 20 calculations, all 24 validations (the priority ladder is rendered as §2.9's ordered rungs), all 48 state-machine transitions, all 3 OCC rules, all 4 SoD pairs, all cross-entity cascades (A/B/C), and every enum value and every state name in the scaffold occur verbatim.
- Contract 3 — §3 Path Purity: **PASS**. No backticked token in the §3 slice starts with `/`, is a bare HTTP method, or combines method+path. HTTP contract lives only in §4.
- Style: no pseudocode or operator syntax (`==`, `<=`, `round_half_up(`, `max(0`, `floor(` all absent) and no fuzzy words ("approximately", "roughly", "etc.").

**Hard constraints honored:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced; no sibling task directory was read. The three contract reports appear here only, never inside PRD.md.

**Scaffold inconsistencies resolved (flagged for the scaffold owner)**
1. `cumulative_drawn_pct`: the entity field text says 6 decimal places while the `construction_trigger_and_seed` calculation and `drawdown_funding_conservation` invariant use 4. PRD states four decimal places, with the threshold comparison made on the rounded value.
2. `termination_compensation.precision` claims the accrued equity return is "the only rounded term", but the `AUTHORITY_DEFAULT` variant also rounds its 10% equity uplift. PRD documents both roundings (half up, once each).
3. Validation priority 42's `applies_to` omits self-report/verify/invoice/pay, though those operations plainly need the concession-state gate; PRD maps them to `ERR_CONCESSION_STATE_FORBIDS_OPERATION` (409).
4. Validation 40 lists dispute adjudication as admitted from `{RAISED, RESUBMITTED}` while the state machine also declares `REFERRED_BACK → …`; PRD follows the state machine (all three).
5. The relief-window buffer prose ("clear gap of more than 2 × 3 days") contradicts its own worked example; PRD uses the buffered closed-interval intersection definition ("at least six clear calendar days; five clear days conflicts, six does not").
6. `net_payment_cents` has no stated default at period creation; PRD derives it from the formula (equal to the frozen `gross_unitary_charge_cents` until verification settles it).

Orchestrator truncation check (per invocation instructions): `tail -c 1200` shows the §5 error table completing normally through `ERR_NO_REFINANCING_GAIN | 422`; `grep -n '^#'` shows all five top-level sections present with §5 last. Not truncated — no regeneration needed.

## Step 6: Generate Implementation — 2026-09-03T11:28:00.000Z

Implementation complete, smoke-tested, and all my own servers shut down (ports 18542 and 18543 confirmed free; no broad `pkill` used).

## Files written
`/home/ubuntu/github/CodingPRD/tasks/task_2542_public_private_partnership_availability_payment_project/workspace/implementation/`

| File | Lines |
|---|---|
| `start.sh` (executable, `exec python3 app.py`, guarded pip install) | 8 |
| `requirements.txt` (`flask>=2.0`) | 1 |
| `app.py` (envelope error handlers, per-request snapshot/rollback, blueprint registration, `0.0.0.0:$PORT` default 10000) | 68 |
| `db.py` (in-memory `Store`, logical clock pinned to `2026-08-01T00:00:00Z`, `touch`/`setf`/`public`, deepcopy snapshot) | 159 |
| `errors.py` (40 error ids → HTTP status, `ApiError`, `fail`) | 78 |
| `response.py` (`meta`/`response_type`/`data`, pagination meta) | 94 |
| `middleware.py` (`X-User-ID`/`X-User-Role`, RBAC, ownership, SoD, 11 resolvers, validators) | 238 |
| `calc.py` (all money/points/allocation/relief/compensation math, `Decimal` + ROUND_HALF_UP) | 517 |
| `routes/reads.py` | 253 |
| `routes/concessions.py` | 206 |
| `routes/periods.py` | 214 |
| `routes/deductions.py` | 188 |
| `routes/relief.py` | 144 |
| `routes/drawdown.py` | 118 |
| `routes/enforcement.py` | 299 |
| `routes/__init__.py` | 0 |

Total 16 files, 2,585 lines. `__pycache__` removed; no seeding, no on-disk state (pure dicts).

## Endpoint count
`app.url_map` enumerates exactly **57** endpoints: 23 GET, 33 POST, 1 PATCH — matching the PRD §4 table (including `/_clock/set_current_utc`, which is deliberately auth-exempt per PRD §2's "single exception" clause).

## Smoke-test result
Two scripted end-to-end runs against a live server (`PORT=18542`), ~120 assertions, **all behaviors correct**. Three initial red lines were wrong expectations in my own script, each re-checked against PRD prose and confirmed the code is right:
- handback survey on a `STEP_IN` concession returns `ERR_CONCESSION_STATE_FORBIDS_OPERATION`, not the enforcement freeze error — PRD line 274 orders the OPERATIONS check before the freeze.
- a claim starting 5 clear days after the prior window's end *does* conflict (PRD line 240: "five clear days conflicts, six does not"); the 6-clear-day case passes.
- a period's `version` is 2, not 1, after rollback because the report submission legitimately bumped it.

Verified fixture arithmetic and behavior, all exact: monthly unitary charge 8,604,167 (masp 100,000,000 @ 3.25%); period cap 1,720,833; report 320 pts vs verified 336 pts → variance exactly 0.0500 (in tolerance, no event) and `availability_ratio` 0.9976; three events of 400/600/500 pts → sequential 500,000/750,000/470,833 and pro-rata 458,888/688,334/573,611 (both summing to the cap); 3-day compensation grant → relief 832,661 and net 7,715,995; 30%-drawdown trigger → CONSTRUCTION + 2% `CONSTRUCTION_SEED` ledger row by `SYSTEM`; dispute uphold cascade (re-price → `PAID→ADJUSTED`); reserve withdrawal guards + reversal replay (`resulting_balance_cents` back to 10,000,000); refinancing tier 0.30 → 15,000,000/35,000,000 shares and 8,750,000 consent sweep; persistent-breach step-in and its clear-by-withdrawal cure cascade across 3 rows; termination compensation (12 elapsed months from 365 days, accrued return 18,000,000) → settle → TERMINATED + WOUND_UP; zero-reported variance = exactly 1 → understatement event of delta×1.25 pts; annual cap gate (1,200,000) refusing at exactly +1 cent with `ERR_ANNUAL_DEDUCTION_CAP_EXCEEDED` and landing on the cap permitted; and full atomicity — the failed verification left no orphan deduction event, no axis move, no `variance_pct`, and no YTD change. Validation ladder spot-checks (401 → 403 → 404-before-400 → 412-before-409) all returned the PRD-mandated error.

The evaluator's literal contract was also exercised: `bash start.sh` with `PORT=18543` booted and served a correct empty-list envelope within 4 seconds.

## Step 5: Generate Unit Tests — 2026-09-03T12:18:00.000Z

Stage 2 is complete. Every live instance in both design indices is now translated, verified, and lint-clean.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_2542_public_private_partnership_availability_payment_project/workspace/`)

New this session (`test_suite/`):
- `test_13_validation_gates_and_ladder_order.py` — 480 lines, 12 tests
- `test_14_endpoint_surface_and_derived_reads.py` — 214 lines, 5 tests
- `test_15_error_catalogue_and_not_found_codes.py` — 406 lines, 11 tests
- `test_16_role_boundaries_and_separated_duties.py` — 312 lines, 6 tests
- `test_17_concurrency_cascades_and_consistency.py` — 399 lines, 6 tests

Previously written and unchanged: `conftest.py` 10; `test_01` 188, `test_02` 291, `test_03` 168, `test_04` 202, `test_05` 180, `test_06` 265, `test_07` 223, `test_08` 166, `test_09` 170 (queue A); `test_10` 535, `test_11` 511, `test_12` 442 (queue B).

Two Stage-1 fixes were required by the new tests: `test_helpers/fixtures.py` (898 lines) — `escalate_enforcement_action` defaulted to an `AuthorityOfficer`, but §4 restricts `POST /escalate` to `LenderAgent`, so the default is now `LENDER`; `test_helpers/factories.py` (281 lines) — added `amend_concession_payload(**fields)` for the partial `PATCH /ppp/concessions/{id}` body. The other seven helper files are untouched.

## Test counts
- Queue A (difficulty): 50 tests over all 24 non-stub instances.
- Queue B (corner): 76 tests over all 76 non-stub instances — entities 14, state_machines 13, calculations 9, validations 12, endpoints 5, errors 11, rbac 6, cross_cutting_complexity_layers 5, consistency_model 1.
- Total: 126 tests, confirmed by `pytest --collect-only` (126 collected).

## Skipped instances
None. Every live instance passed the PRD-first two-condition filter, so nothing was dropped for PRD silence or non-unique-derivability. The 26 corner entries carrying `excluded_because:` were left untranslated by design (a script confirms zero stub tags).

Where a recipe's expected value contradicted the PRD, the PRD won and the divergence carries an inline comment. New cases this session: `deduction_points_total` is the sum of `points` over the period's live events (so 400 after one 400-point event, and 238 for the understatement event, not the recipe's 320); a period with no events reports `total_deduction_cents` 0 and `net_payment_cents` 8604167 rather than null; the positive control for the step-in ground test uses `LENDER_DEFAULT_CURE` because `PERSISTENT_BREACH` additionally requires `persistent_breach_flag`, which the recipe's fixture never sets.

## Verification run at the end
- Every test docstring carries exactly one `Design:` line: 126 tests, 126 tags, zero untagged/dual-tagged (AST scan).
- Tag/index cross-check: 76 distinct corner tags == the 76 LIVE instances (zero missing, zero bogus, zero stubs, no instance double-covered); 24 distinct difficulty instances.
- Citation pass: all 137 `PRD: "…"` quotations found verbatim in `PRD.md` after whitespace normalisation.
- No occurrence of "scaffold", "design index", `skip`, `xfail`, `mock` or `monkeypatch` anywhere in `test_suite/` or `test_helpers/`.
- `python3 -m py_compile` OK and `python3 -m pyflakes` clean over all 9 helper files and all 18 suite files; each of the 17 test modules imports successfully against the real helper package, so every fixture, factory and client method referenced exists.

### Orchestrator note — path correction (not a content change)

The subagent wrote both directories inside `workspace/` (`workspace/test_helpers/`, `workspace/test_suite/`), but the pipeline's output contract places them at the task-directory root as siblings of `workspace/`. The orchestrator ran `mv workspace/test_helpers workspace/test_suite .`. Since both moved together, `test_helpers` remains the sibling of `test_suite` that `from test_helpers import ...` relies on; `python3 -m pytest test_suite --collect-only -q` re-confirms **126 tests collected** at the new location. No file contents were edited. Note also that the impl generator (Step 6) never had these directories visible under either path — Step 6 finished at 11:28 and the first test file landed at 12:09.

## Step 7: Run Tests and Iterate — 2026-09-03T12:41:00.000Z

All 8 parallel rounds now pass 126/126. Done.

## Summary

**Iterations run:** 2 sweeps (8 parallel rounds each, 126 tests per round).

- **Sweep 1:** 117/126 in *all eight* rounds — 9 failures, identical in every round (fully deterministic, no flakiness; the interleaved `sweep.log` initially looked flaky but the per-round `results.$i.json` were byte-consistent).
- **Sweep 2:** 126/126 in all eight rounds.

### Failure clusters diagnosed

**Cluster A — 6 tests: `cure_deadline` / `effective_date` serialized as a timestamp instead of a calendar date** (`'2027-07-01T00:00:00.000Z' == '2027-07-01'`). PRD §3.11 states verbatim: *"sets its `cure_deadline` to the `effective_date` plus 90 calendar days"* and, for the escalation successor, *"`effective_date` equal to the current logical clock"*. `effective_date` is a `_date` field the server stores verbatim as the caller's date, and PRD §2.6 says all spans are whole calendar days; §2.4 reserves the 3-fractional-digit ISO instant form for clock-stamped `created_at`/`updated_at`. Adding calendar days to a date yields a date — the timestamp reformat was implementation-invented. **Implementation fix.**

**Cluster B — 3 tests: `certified_cost_cents is None` on a pre-approval milestone** (`assert 0 is None`). PRD is silent: the create paragraph specifies only `status` and `sequence_no`, and the reject branch's null enumeration (*"`approved_at`, `disbursed_at`, `equity_portion_cents` and `debt_portion_cents` are all left null"*) conspicuously omits `certified_cost_cents`, even though this PRD is elsewhere meticulous about null-vs-0 (cf. the drafting paragraph: *"…are all null, `ld_accrued_cents` is 0"*). Two PRD-faithful readers diverge (null vs. 0 vs. field absent until approval). **DEFAULT-VALUE SILENCE → assertion deleted** (STEP 1c partial-coverage split; each test's headline rule stayed).

**Latent 4th failure** surfaced by fixing Cluster A: `assert action["resolved_at"] is None`. `resolved_at` appears nowhere in PRD.md (PRD names `cured_at`/`settled_at`) and only once in the whole suite — a `KeyError` waiting behind the `cure_deadline` assert. **Deleted.**

### Fixes applied to `implementation/`
- `workspace/implementation/db.py` — added `format_date()` and `is_date_only()` helpers (calendar-date rendering; raw-input shape detection).
- `workspace/implementation/routes/enforcement.py`, `notify_action()` — `cure_deadline` now renders as a calendar date when `effective_date` was supplied as one (falls back to the instant form otherwise). Comparison semantics untouched: `as_instant("2027-07-01")` still parses to the midnight instant, so the cure/escalate partition at the deadline is unchanged (verified: escalation at exactly `2027-07-01T00:00:00Z` still returns `ERR_CURE_WINDOW_VIOLATION`).
- `workspace/implementation/routes/enforcement.py`, `escalate_action()` — the system-appended termination's `effective_date` is now the logical clock's calendar day rather than a full instant.

### Fixes applied to `test_helpers/`
None — no fixture, factory, or role-header helper was inconsistent with PRD.

### Tests deleted (assertions only; no test function removed, no skip/xfail, no error_id weakened)
- `test_11_state_machine_transitions.py::TestMilestoneCreationInitialState` — `certified_cost_cents is None` (DEFAULT-VALUE SILENCE; scaffold rule `Corner/state_machines/a_new_milestone_starts_in_requested_with_no_split_computed`).
- `test_11_state_machine_transitions.py::TestMilestoneRejectionIsTerminal` — `certified_cost_cents is None` (DEFAULT-VALUE SILENCE; `Corner/state_machines/milestone_rejection_is_terminal_and_moves_no_drawn_total`).
- `test_11_state_machine_transitions.py::TestApprovingARejectedMilestoneIsLockedOut` — `certified_cost_cents is None` (DEFAULT-VALUE SILENCE; `Corner/state_machines/approving_an_already_rejected_milestone_is_locked_out`).
- `test_13_validation_gates_and_ladder_order.py::TestEscalationOnTheDeadlineInstant` — `resolved_at is None` (COMPUTED-FIELD SILENCE / field absent from PRD entirely; `Corner/validations/escalation_exactly_on_the_cure_deadline_is_still_premature`).

Storage remains in-memory dicts only (no SQLite, no JSON dump, no `/tmp` cache); no entity is seeded at startup. My private diagnostic server on port 18542 was killed by pid; no broad `pkill` was ever issued.

### Orchestrator verification (per memory note: never take a claimed clean sweep on faith)

The orchestrator independently re-read all eight `workspace/implementation/results.$i.json` (all mtime 12:36, i.e. post-fix) and parsed `passed`/`total` from each: **126/126 in all eight rounds**. The artifacts exist and confirm the subagent's claim.

## Step 8: Finalize PRD — 2026-09-03T12:45:00.000Z

`PRD_FINALIZED.md` is written.

## Size
- PRD.md: 425 lines / 100,752 bytes; PRD_FINALIZED.md: 425 lines / 101,745 bytes.
- Line delta: 0 (0.0%); byte delta: +993 (+0.99%). 6 lines touched, no sections added.

## Changes
- §3.11 (notify paragraph) — revise — `effective_date` is recorded verbatim in the shape the caller supplied (a bare `YYYY-MM-DD` stays a bare date, never widened to an instant) — `routes/enforcement.py:108,129` (`raw_effective` from `middleware.req_instant:221-233`).
- §3.11 (step-in arm) — revise — `cure_deadline` = `effective_date` + 90 calendar days *rendered in the same shape as the `effective_date`*: date-only in → date-only out, time component in → three-fractional-digit instant form of §2.4 — `routes/enforcement.py:153-155` with `db.format_date:74`, `db.is_date_only:79`.
- §3.11 (cure/escalate partition) — insert — both window predicates read the stored `cure_deadline` *as an instant*, a bare calendar date meaning midnight UTC at the start of that day — `routes/enforcement.py:173-175, 195-197` + `db.parse_instant:38`.
- §3.11 (escalation successor) — revise — the appended termination's `effective_date` is the logical clock's *calendar day*, written as a bare `YYYY-MM-DD` date, not a full instant — `routes/enforcement.py:207`.
- §3.2 (milestone creation) — insert — a new milestone's `certified_cost_cents` is initialised to `0`, not null — `routes/drawdown.py:42`.
- §3.2 (rejection branch) — revise — `certified_cost_cents` is not written on rejection and so keeps the `0` it was created with (the existing null enumeration left untouched) — `routes/drawdown.py:82-89`.

No edit made for the deleted `resolved_at` assertion: the field exists nowhere in `implementation/` (grep confirms zero hits) and nowhere in PRD, so PRD-silence already yields the impl behaviour; adding prose would have invented a field.

## Per-edit pre-edit search log
1. **`effective_date` recording (enforcement)** — (b) grepped `effective_date` across `implementation/`: only `routes/enforcement.py:108,129` (caller's raw string) and `:207` (system successor); read `middleware.req_instant` (returns raw + parsed, raw is what's stored) and `routes/reads.py` (all reads return `public(row)` with no reformatting/projection). (c) scoped the verbatim claim to the caller-supplied notification path so the escalation-appended row at `:207` is not mis-described; wording says "the shape the caller supplied it", which is silent about system-generated rows.
2. **`cure_deadline` rendering** — (b) grepped `format_date` / `format_instant` / `is_date_only` across the whole impl: `format_date` used only at `enforcement.py:154` and `:207`; `is_date_only` only at `:154`; `cure_deadline` written only at `:130` (null at insert), `:154` (step-in) and `:208` (successor null); read `is_date_only` (strip, len==10, no `T`/`t`/space) and `_ISO_RE` (any non-date-only accepted form necessarily has a time component, so the two branches are exhaustive). (c) phrased the fallback branch as "carrying a time component" rather than "supplied as an instant", because inputs like `2027-04-02T10:00` with no zone also take the instant branch; kept "the three-fractional-digit instant form of §2.4" since `format_instant` normalises to UTC with `Z`.
3. **Cure-window instant reading** — (b) read both consumers of the deadline (`cure_action:173-175`, `escalate_action:195-197`), `db.parse_instant` (bare date → midnight UTC), and the parallel cure path `calc.cure_persistent_breach_step_in:243-256` which cures without consulting the deadline at all. (c) wrote "Both predicates" (the two lender-initiated calls of that paragraph) instead of a universal "every cure", so the §3.6 cascade cure — which ignores the window — stays correctly described by the existing prose.
4. **Successor `effective_date`** — (b) `enforcement.py:200-226` (the only append site), plus every downstream reader of `effective_date`: grep shows none — no calc, guard, ordering or comparison reads it, so a date-shaped value cannot change any decision. (c) none; wording is a plain narrowing of "the current logical clock" to its calendar day.
5. **Milestone `certified_cost_cents` default** — (b) grepped `certified_cost_cents`: `drawdown.py:42` (create, 0), `:60,68` (approve, caller value), `calc.py:328-335` (`drawdown_split` parameter only); confirmed `reject_milestone:76-90` never assigns it and requires `REQUESTED`, and checked §3.2's funding-identity paragraph (sums over *disbursed* milestones only, unaffected by a 0 default on non-approved rows). (c) added "rather than to null" but deliberately avoided any claim about `equity_portion_cents`/`debt_portion_cents` at create time (those are null and PRD's existing prose already covers them).
6. **Rejection leaves `certified_cost_cents` alone** — (b) same enumeration as #5, plus `db.setf:163` (assignment only bumps version when the value changes, so the reject branch's four null writes are no-ops and no `certified_cost_cents` write exists on any path out of `REQUESTED → REJECTED`). (c) said "is not written at all and so keeps the 0 it was created with" instead of "is 0", so the sentence stays true by construction rather than asserting a value that some other path might change.

Orchestrator verification: `workspace/PRD_FINALIZED.md` exists (101,745 bytes, 425 lines) and a folded `diff` against `PRD.md` confirms it is a real, non-empty minimal patch rather than a byte-identical copy.

## Step 9: Complete PRD — 2026-09-03T13:03:00.000Z (pass 1 of 3)

Orchestrator note on method: per prior experience on this pipeline, a single-subagent Step 9 over a ~100KB PRD with 57 endpoints tends to no-op (PRD_COMPLETED.md comes back byte-identical to its source, meaning the scan never really ran). Step 9 was therefore run as **three sequential file-partitioned passes**, all editing the same `workspace/PRD_COMPLETED.md`: pass 1 = cross-cutting layers (`app.py`, `db.py`, `errors.py`, `response.py`, `middleware.py`); pass 2 = `calc.py` + `routes/concessions.py|drawdown.py|periods.py`; pass 3 = `routes/deductions.py|relief.py|enforcement.py|reads.py` plus a final §4/§5 consistency check. Each pass was told not to redo the previous passes' slices and never to `Write` the file whole (output-cap truncation would destroy prior passes' work).

### Pass 1 subagent summary (verbatim)

Pass 1 complete.

**Working file created:** `cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md`.
- Before: 425 lines / 101,745 bytes. After: 425 lines / 107,058 bytes (+5,313 bytes, no line-count change — all edits are in-paragraph; heading count unchanged at 30; the JSON envelope fenced block is intact).

**Counts:** 11 ambiguity-pins, 3 mismatch-revisions (14 edits total).

**Changes**
- §2.1 Parties, Roles and Access Control — insert — ambiguity — header requirement scoped to the `/ppp` surface (clock utility excluded); `X-User-ID` that is present but empty/whitespace-only is also `ERR_UNAUTHENTICATED`; role compared case-sensitively with no trimming — `middleware.py:30-35`.
- §2.2 Standard Success Response Format bullet — insert — ambiguity — `api_request_id` is `req_` + exactly twenty upper-case-alphanumeric characters — `response.py:17-21`.
- §2.2 Standard Success Response Format bullet — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not wall clock, so responses at the same clock value share it — `response.py:24-28`.
- §2.3 Pagination — revise — mismatch — `limit`/`offset` are clamped (1–100, ≥0) and non-integer/empty values fall back to defaults; they are never a ground for rejection; `meta` echoes the effective values (PRD's "may not be below/exceed" read as rejection) — `response.py:44-61`.
- §2.3 Pagination — insert — ambiguity — `created_at` ties (routine, since the clock only moves on demand) are broken by insertion order via an internal counter that appears in no response field (also pins the `public()` projection hiding `_`-prefixed fields) — `db.py:120`, `db.py:172`.
- §2.4 Resource Identity, Audit Stamps — insert — ambiguity — the `updated_at`/`version` bump is once per row per request however many fields move, and an assignment that leaves a field unchanged is not itself a mutation — `db.py:147-168`.
- §2.6 Logical Clock — revise — mismatch — the clock endpoint performs no authentication and no role check, so the `PlatformAdmin` in §4 is the expected operator, not an enforced restriction — `app.py:23-24` + absence of `require_auth` at `routes/enforcement.py:300-305` (verified, not edited for).
- §2.6 Logical Clock — insert — ambiguity — the clock may be moved backwards as freely as forwards — `routes/enforcement.py:300-305` (no monotonicity guard) / `db.py:107-108`.
- §2.6 Logical Clock — insert — ambiguity — accepted instant grammar (date-only; `T` or space separator; optional seconds and 1–9 fractional digits; `Z` or `±HH:MM`/`±HHMM` normalised to UTC; bare value read as UTC; impossible calendar dates rejected), server stamps always 3-digit `Z`, and caller-supplied instants persisted/echoed verbatim while only comparisons use the normalised value — `db.py:31-71`, `middleware.py:221-233`.
- §2.8 Segregation of Duties — insert — ambiguity — a null recorded identifier means there is nothing to compare and no violation — `middleware.py:58-61`.
- §2.9 Rejection Precedence (ladder) — revise — mismatch — path-id existence now precedes concessionaire ownership (impl resolves the row, then `owner_guard`) — `middleware.py:51-55` with call order at `routes/drawdown.py:23-25`, `routes/periods.py:75-77`.
- §2.9 Rejection Precedence — insert — ambiguity — third "easy to get wrong" consequence: a `Concessionaire` naming an unresolvable path id gets 404, not the ownership 403 — same call order as above.
- §2.9 body-id rung — insert — ambiguity — only a well-formed non-empty identifier string reaches the `ERR_REFERENCED_ENTITY_NOT_FOUND` rung; absent/null/empty/non-string falls through to the schema rung — `routes/concessions.py:46-53` gate over `middleware.py:152-164`.
- §2.9 schema rung — insert — ambiguity — body must be a JSON object (absent/empty body = empty object, content type never examined, non-object JSON refused), `null` counts as absent, booleans never accepted for integer/decimal fields, empty/whitespace-only or over-length strings refused, excess decimal places refused rather than rounded — `middleware.py:137-206`.
- §2.10 Resource Addressing — insert — ambiguity — trailing slash insignificant; routing-level refusals use the standard envelope with `ERR_INVALID_REQUEST` at the routing status (404 unknown path, 405 unadmitted method) and unexpected internal failures likewise at 500 — `app.py:24,47-59`.
- §2.11 Cascade Discipline — insert — ambiguity — full request atomicity: pre-handler whole-store snapshot restored on any rejection, so no partial row, no half-applied cascade, no version bump, no consumed `sequence_no`, no moved clock — `app.py:27-59`, `db.py:122-126`.
- §5 catalogue preamble — insert — ambiguity — statuses in the table hold for requests that reach the business surface; the one qualification is the routing-level/internal use of `ERR_INVALID_REQUEST` per §2.10 — `app.py:47-59`.

**Already uniquely pinned (checked, no change):** the success/error envelope key sets and `response_type` values (`object`/`array`/`error`); error `meta` carrying only the two request fields; 201-on-create vs 200 otherwise and `{}` data for empty 2xx; `total_count` pre-pagination and the `has_more` definition; the complete error-id→HTTP-status table in §5 (matches `errors.ERROR_STATUS` entry for entry, all 41); `ERR_UNAUTHENTICATED` evaluated before role authorization, and `ERR_ROLE_NOT_PERMITTED` for a recognised-but-unpermitted role; the five role spellings; ownership applying only to `Concessionaire` via the owning concession's `concessionaire_id` with `ERR_NOT_CONCESSION_PARTY`; opaque operator ids never compared to entity ids and `SYSTEM` sentinel semantics; UUID `id` with no prefix, never an input, never an ordering key; `created_at` stamped from the logical clock in 3-digit-`Z` form; reserve transactions as the single append-only type without `updated_at`/`version` (`insert(..., versioned=False)`); startup clock `2026-08-01T00:00:00Z` and clock-set writing no business row; the three optimistic-concurrency operations, their field names, their 412 error ids, and "no version field ⇒ no check"; the four segregation-of-duties pairs and 403.

**Flagged for the parent, not edited by me (outside my slice):** `routes/enforcement.py:300-305` implements `/_clock/set_current_utc` with no `require_auth`, so §4's role column for that row is unenforced — I pinned this in §2.6 prose rather than rewriting the §4 table cell, in case pass 2/3 owns the endpoint table.

## Step 9: Complete PRD — 2026-09-03T13:11:00.000Z (pass 2 of 3)

### Pass 2 subagent summary (verbatim)

**PASS 2 of 3 — PRD completeness scan, task 2542**
Slice: `implementation/calc.py`, `routes/concessions.py`, `routes/drawdown.py`, `routes/periods.py`

**File counts**
- Before: 425 lines / 107,058 bytes
- After: 425 lines / 110,142 bytes (+3,084 bytes; no new sections, no line-count change — all edits are in-paragraph)

**Counts:** 10 ambiguity-pins, 4 mismatch-revisions (14 `Edit` calls total)

**Changes**
- §3.4 (verification, availability ratio) — insert — ambiguity — pinned that the ratio is composed in full and rounded once at the end, and that verified minutes are **not** capped against the period's total minutes, so an over-large verified count yields a negative ratio published as computed rather than clamped — `calc.py:123-127`, `periods.py:155-156`
- §3.4 (self-reporting) — insert — ambiguity — pinned the two error ids on report creation: reporting axis outside `PENDING`/`SELF_REPORTED` → `ERR_INVALID_STATE_TRANSITION` (409), concession not `OPERATIONS` → `ERR_CONCESSION_STATE_FORBIDS_OPERATION` (409) — `periods.py:85-88`
- §3.4 (report rejection) — insert — ambiguity — `rejection_reason` non-empty, max 2,000 chars — `periods.py:116`
- §3.4 (verification order) — **revise** — **mismatch** — PRD said the axis advances "only when all of that has succeeded"; impl advances `SELF_REPORTED → VERIFIED` and stamps `verified_at` **after** the cap gate but **before** recomputing the concession totals, and that order is load-bearing because the YTD sum reads only `VERIFIED` periods. Revised to pin the true order and say why — `periods.py:169-177`
- §3.3 (opening a period) — insert — ambiguity — `days_in_period` must be at least 1; a `period_start`/`period_end` pair on the same calendar day spans zero days and is `ERR_INVALID_INTERVAL` despite being strictly ordered — `periods.py:31-33`
- §3.8 (payment) — insert — ambiguity — `payment_reference` non-empty, max 200 chars — `periods.py:205`
- §3.8 (`ADJUSTED` routes) — **revise** — **mismatch** — PRD applied the "only where `total_deduction_cents` genuinely differs" test to all three re-pricing routes; impl applies it only to upheld-dispute and withdrawal, and moves the period **unconditionally** on a granted compensation event. Split the sentence accordingly — `calc.py:210-215` (`mark_adjusted_if_repriced(unconditional=)`), caller `relief.py:99`
- §3.8 (payment summary) — insert — ambiguity — summary also carries the concession's own id as `concession_id` — `calc.py:507`
- §3.2 (milestone rejection) — insert — ambiguity — `rejection_reason` non-empty, max 2,000 chars — `drawdown.py:81`
- §3.9 (handback shortfall charge) — **revise/insert** — **mismatch** + ambiguity — pinned that the system event carries `issued_by_user_id` `SYSTEM` and a null `performance_report_id`; that the concession's `availability_deduction_ytd_cents`, `deduction_points_ytd` and `persistent_breach_flag` are recomputed after the re-pricing; that the charge is **not** tested against the annual deduction cap and does **not** move a `PAID` period to `ADJUSTED`; and that with no verified period at all the survey records `FAILED` and raises no event — `concessions.py:197-205`, `calc.py:377-382`
- §3.5 (annual cap gate scope) — **revise** — **mismatch** — "whenever a deduction is issued against a period that is already `VERIFIED`" was false for the handback cascade; narrowed to an officer-issued deduction and named the handback-shortfall charge as the sole exempt deduction — absence of `annual_cap_guard` at `concessions.py:197-205` vs `deductions.py:56`
- §3.9 (survey preconditions) — insert — ambiguity — `handback_status` is not a guard: an already `CERTIFIED`/`FAILED` concession may be surveyed again, overwriting all four handback fields and raising a further shortfall event on a fresh failure — `concessions.py:186-195`
- §3.7 (relief-day annual budget) — insert — ambiguity — the 60-day budget sums `granted_relief_days` over live claims of **every** `claim_type`, not just `RELIEF_EVENT` — `calc.py:473-478`
- §2.9 (body-id rung) — insert — ambiguity — "empty" means the exact empty string, so a whitespace-only body id **is** looked up and yields `ERR_REFERENCED_ENTITY_NOT_FOUND` rather than a schema failure — `concessions.py:49-53` (same shape at `deductions.py:32-36`). This touches pass 1's paragraph; the addition is appended to the end of that sentence only.

**Checked and already uniquely pinned (no change)**
`monthly_unitary_charge_cents` single-rounding chain; `annual_cap_cents` (MASP×10%); point weighting 2/40/10 for both report and verification; `variance_pct` four-dp with the reported-zero → 0/1 split and write-only-onto-the-`SUBMITTED`-report rule; understatement uplift ×1.25 on the delta with the strict >0.05 tolerance (the impl's `points > 0` guard is provably dead); sequential waterfall over `ISSUED`/`DISPUTED` in ascending `sequence_no`; pro-rata floor + residue distribution ordered by `raw_amount_cents` desc then `sequence_no` asc with wrap-around; `deduction_points_total`; the pinned four-step cap→total→relief→net chain with the excess floored at zero; relief credit as a merged day-union clipped to the half-open period, capped at `days_in_period`, single rounding, zero-days → exactly 0; `recompute_ytd` over `VERIFIED` periods; points/breach recompute over all periods' live events with the inclusive 500 threshold, recomputed-not-latched, and the true→false cure cascade (action `CURED`, `cure_note` `PERSISTENT_BREACH_CLEARED`, `cured_at`, concession `STEP_IN → OPERATIONS`, sponsor `STEPPED_IN → ACTIVE`); strict annual-cap comparison; `sequence_no` = max+1 for events/milestones/ledger; `raw_amount_cents` = points×1250; equity-first split (min of 30%-of-TPC rounded and committed equity, room floored at zero) and the three `ERR_COMMITMENT_EXCEEDED` tests; `cumulative_drawn_pct` 4-dp; the inclusive 0.30 construction trigger compared against the rounded ratio, one-shot, with the 2%-of-TPC `CONSTRUCTION_SEED` `CONTRIBUTION`/`SYSTEM` entry; LD gross→excused (`RELIEF_EVENT` only, live statuses)→net floored→×rate→min with cap; handback single-pass penalty on the pre-penalty shortfall and `CERTIFIED`/`FAILED` split; latest-verified-period by highest `period_index`; refinancing gain and the 0.5/1.5 MASP bands with inclusive-downward boundaries at 30/50/60%; all four termination-compensation variants incl. 30-day-basis truncated months, single-rounded accrued return, separately-rounded 10% authority-default uplift, offsets from `allowed_amount_cents` over live events, clamp at zero; relief notification ≤20 days with negative→0; ±3-day same-type window conflict over `NOTIFIED`/`GRANTED`/`PARTIALLY_GRANTED`; `periods_touching_window`; payment-summary field set; concession drafting field bounds/defaults and the `ERR_COMMITMENT_EXCEEDED` sum test; `concessions_count` as a live recount; PATCH restricted to `DRAFTED` with no charge re-derivation; financial close preconditions; commencement's three guards and its `ERR_INVALID_STATE_TRANSITION` for a second certification; period freezing of `gross_unitary_charge_cents`/`deduction_cap_cents`, half-open overlap with adjacency permitted, `ERR_DUPLICATE_PERIOD_INDEX`, and all null/zero initial values with `net_payment_cents` = gross; supersede-in-place resubmission and the revert edge on rejection; the exactly-one-`SUBMITTED` rule and the verify-side SoD over any attached event; invoice/pay preconditions and the two-axis independence; the enforcement freeze set (`NOTIFIED`/`STEP_IN_ACTIVE`/`COMPENSATION_CALCULATED`) applying to milestone create, disburse and handback survey but **not** to approve/reject/period-open.

**Flagged for pass 3 (seen but not edited — outside my files)**
1. `deductions.py:54-56` — `issue_event` does `projected = calc.recompute_ytd(concession)` (recompute **then** gate). PRD §3.5 defines the projection as "current `availability_deduction_ytd_cents` plus the period's recomputed `total_deduction_cents`". For a period **not** yet `VERIFIED` the newly issued deduction is excluded from the projection entirely, so the annual cap cannot bite there — likely a mismatch needing §3.5 revision.
2. `deductions.py:57` — `issue_event` never calls `mark_adjusted_if_repriced`, so issuing a fresh deduction against an already-`PAID` period leaves it at `PAID`. Cross-check against §3.5's "the whole chain is reversible" claim and the §3.8 `ADJUSTED` enumeration.
3. `deductions.py:101-108` — `raise_dispute` returns `ERR_DISPUTE_ALREADY_OPEN` only when the event is `DISPUTED` *and* a dispute is open; other non-`ISSUED` states give `ERR_INVALID_STATE_TRANSITION`. PRD §3.6 names no id for "event must be in `ISSUED`".
4. `deductions.py:68` / `130` / `147` / `167` — `withdrawal_reason`, `referred_back_reason`, `grounds` (resubmit) and `outcome_note` all max 2,000 chars; PRD states the limit only for the initial `grounds`.
5. `deductions.py:38-42` — an officer naming a system-only `deduction_type` gets `ERR_INVALID_REQUEST` (400) *after* enum validation; PRD §3.5 calls them system-only without naming the error.
6. `relief.py:63-65` — `granted_relief_days` and `granted_cost_cents` default to 0 and `determination_note` to null when absent; §3.7 says only "optional".
7. `relief.py:119` — the withdrawal floor is tested against `reserve_balance()` (last ledger entry) rather than the concession field; equal in practice, worth a glance.
8. `routes/reads.py` and `routes/enforcement.py` were not reviewed in this pass at all.

## Step 9: Complete PRD — 2026-09-03T13:35:00.000Z (pass 3 of 3 — final)

### Pass 3 subagent summary (verbatim)

Pass 3 complete. All edits are in-paragraph; the file is intact.

## Integrity
- **Before:** 425 lines / 110,142 bytes. **After:** 425 lines / 116,572 bytes (+6,430; line count unchanged — every edit was an in-paragraph insert/revision).
- `tail -c 600` ends at the §5 error table's last row `` | `ERR_NO_REFINANCING_GAIN` | 422 | ``. Both §2.2 ```json fences present (2). 30 section headers, 101 table rows (§4: 57 data rows; §5: 40 data rows), unchanged.
- Line-by-line diff vs `PRD_FINALIZED.md` shows exactly 40 changed lines: the 21 from passes 1–2 are all still present, plus my 19 lines. No pass-1/2 work clobbered.

## Counts
**21 edits: 16 ambiguity-pins, 5 mismatch-revisions.**

## Changes
- §2.3 — insert — ambiguity — filter semantics: exact case-sensitive string match, absent/empty value not applied, null field matches no value, conjunctive narrowing, no-match yields empty array + `total_count` 0 (not 404/400), unrecognised query params ignored — `reads.py:22-29`
- §2.9 (ladder) — insert — ambiguity — added the enforcement-ground-admissibility rung between the target-row-state and owning-concession-state rungs — `enforcement.py:110-122`
- §2.9 (schema) — insert — ambiguity — default string maxima where §3 states none: 2,000 for note/reason/grounds, 200 for a name/external reference, 500 for a reserve-ledger `reason`; body identifiers unbounded — `deductions.py:68,130,147,167`, `relief.py:65,132`, `enforcement.py:170,279`
- §3.5 — insert — ambiguity — officer naming a system-only `deduction_type` → `ERR_INVALID_REQUEST` (400) at the schema rung, tested *after* `points`; plus no precondition on either of the period's status axes — `deductions.py:38-42`
- §3.5 — **revise** — **mismatch** — annual-cap projection redefined as the sum of `total_deduction_cents` over `VERIFIED` periods taken after re-pricing, with the two call-site forms spelled out (verification: current ytd + this period; issue: recomputed in place, so a non-`VERIFIED` period's new charge is invisible to the cap) — `deductions.py:54-56` / `periods.py:169-172`
- §3.5 — **revise** — **mismatch** — gate fires on *every* officer-issued deduction whatever the period's reporting status, not only against an already-`VERIFIED` period — `deductions.py:55-56`
- §3.5 — insert — ambiguity — withdrawal outside `ISSUED`/`DISPUTED` → `ERR_INVALID_STATE_TRANSITION` (409); withdrawal gated on no concession state — `deductions.py:69-70`
- §3.6 — insert — ambiguity — raise-dispute state ids: `WITHDRAWN`/`OVERTURNED` → `ERR_INVALID_STATE_TRANSITION`; `DISPUTED` with an open dispute → `ERR_DISPUTE_ALREADY_OPEN` reported at the *state* rung, ahead of the period check — `deductions.py:101-108`
- §3.6 — insert — ambiguity — none of the four dispute operations is gated on concession `status` or frozen by enforcement — `deductions.py:91-188`
- §3.7 — insert — ambiguity — claim notification gated on no concession state, not frozen by enforcement — `relief.py:22-37`
- §3.7 — insert — ambiguity — determination defaults: granted figures 0, `determination_note` null — `relief.py:63-65`
- §3.8 — insert — ambiguity — the three re-pricing routes are the only ones into `ADJUSTED`; a fresh deduction against a `PAID` period re-prices it but leaves the axis at `PAID` (as does the §3.9 handback charge) — `deductions.py:57`
- §3.9 — insert — ambiguity — ledger append gated on no concession state, not frozen by enforcement — `relief.py:104-123`
- §3.9 — **revise** — **mismatch** — "Three refusals" → "Two refusals, tested in this order"; the `ERR_CROSS_ENTITY_MISMATCH` refusal is unreachable because the flat path names the target entry alone and derives the concession from it — `relief.py:126-138`
- §3.11 — insert — ambiguity — termination arm admitted against any concession status but `TERMINATED` — `enforcement.py:118-122`
- §3.11 — insert — ambiguity — the freeze list is exhaustive; notifying a further action is not frozen — `enforcement.py:101-122`
- §3.11 — insert — ambiguity — on escalation the sponsor vehicle stays `STEPPED_IN` — `enforcement.py:188-228`
- §3.11 — insert — ambiguity — the three-input 400 is taken at the schema rung ahead of the status/`action_type` checks; under other grounds an omitted optional input stays null — `enforcement.py:239-249`
- §4 (preamble) — **revise** — **mismatch** — ownership check applies only where the path resolves to a row with an owning concession; the sponsor-vehicle read and *every* collection read are unscoped — `reads.py:33-36,54-61` and all list handlers
- §4 (clock row) — **revise** — **mismatch** — row description now records: 200 + empty `data`, and that this row is the exception to the role column's exhaustiveness (no auth, no role check) — `enforcement.py:300-305`
- §5 (preamble) — insert — ambiguity — the state rung carries `ERR_INVALID_STATE_TRANSITION` (409) throughout unless §3 names a narrower id — `deductions.py:69,131,148,168`, `relief.py:66`, `enforcement.py:79,171,193,248,280`

## Disposition of the 8 handed-off leads
1. **`deductions.py:54-56` cap projection** — **edited** (mismatch). Confirmed genuine: `recompute_ytd` sums only `VERIFIED` periods, so at issue the PRD's "current ytd + period total" both double-counts a `VERIFIED` period and wrongly includes a non-`VERIFIED` one. Cross-checked `periods.py:169-172`, where the PRD's original formula *is* correct; the revision states both forms so §3.4's ordering claim still holds.
2. **`deductions.py:57` no `mark_adjusted_if_repriced`** — **edited** as a silence in §3.8, not a mismatch. §3.5's "the whole chain is reversible" claim is *sound*: after issue+withdraw the total returns to `_total_deduction_at_paid`, so the conditional check in `mark_adjusted_if_repriced` correctly declines to move the axis — the period ends back at `PAID`. I re-read pass 2's restructured §3.8 sentence and inserted after the `PAID → ADJUSTED` clause, leaving pass 2's compensation-event branch untouched.
3. **`deductions.py:101-108` dispute state ids** — **edited** (ambiguity), including the ordering quirk that the `DISPUTED`+open case is reported at the state rung rather than at §2.9's uniqueness rung.
4. **2,000-char limits** — **edited** (ambiguity) as one global fallback in §2.9 rather than 7 local inserts. Grepped every `req_str` call: the four named plus `determination_note`, `cure_note` (2,000), `settlement_reference` (200) and the reversal `reason` (500) were all silent; `grounds`, `payment_reference`, ledger `reason`, `legal_name`, `project_name`, `milestone_name` and both `rejection_reason`s were already stated in §3.
5. **`deductions.py:38-42` system-only type** — **edited** (ambiguity), including the ordering detail that the refusal follows `points` validation.
6. **`relief.py:63-65` defaults** — **edited** (ambiguity). §2.9's "optional, it takes its documented default" made the missing defaults load-bearing.
7. **`relief.py:119` withdrawal floor** — **no edit.** Verified equal in practice and unfalsifiable: `concessions.py:99` initialises `lifecycle_reserve_balance_cents` to 0, `reserve_balance()` returns 0 for an empty ledger, and every append goes through `append_ledger` → `replay_ledger`, which sets the concession field from the same last-entry value. §3.9's stated identity already pins it.
8. **`/_clock/set_current_utc` and the §4 table** — **edited.** §2.6 already carried pass 1's prose, but §4's preamble claims the role column is exhaustive and 403-enforced, which is a live mismatch for that row. I put the carve-out in the row's own Description cell (and folded in the 200-with-empty-`data` shape), leaving the preamble's general rule intact.

## Checked and already uniquely pinned (no edit)
`enforcement.py`: refinancing gain/tier/share/residual arithmetic and the `PROPOSED` field set; the `OPERATIONS` + freeze preconditions on propose and consent; consent's guard order (version → refi state → concession state → SoD → freeze) matching §2.9 exactly; both consent branches bumping the concession `version`; the `CONTRIBUTION`/`SYSTEM`/`REFINANCING_GAIN_SWEEP` sweep entry; step-in ground admissibility and the `persistent_breach_flag` precondition; the three-row step-in cascade with the shape-matched `cure_deadline`; cure/escalate partitioning the timeline at the deadline instant inclusively; escalation's `LAPSED` + appended bare-date `NOTIFIED`/`CONCESSIONAIRE_DEFAULT`/`SYSTEM` row and `escalated_to_action_id` back-link; all four compensation formulae, the three shared terms, the zero clamp and "no concession field moves yet"; settle's SoD, the three-link cascade and the `INVOICED`-only sweep. `relief.py`: closed-window `ERR_INVALID_INTERVAL`, the 20-day notification window, the ±3-day same-type conflict rule, guard order (notification → interval → conflict) matching §2.9's ladder verbatim, the 60-day budget before the grant ceiling, `GRANTED`/`PARTIALLY_GRANTED` read off the figures, `REJECT` forcing 0/0, the compensation-event cascade running relief-credit-then-net only (no re-allocation) with `unconditional=True`, `periods_touching_window`'s half-open/closed intersection, and the ledger append/reversal signed-amount and `sequence_no` rules. `reads.py`: all 24 GET paths and every role column verified against §4 rows 322–344 (exact match, including `NON_CERTIFIER`, `REPORT_ROLES`, `EVENT_ROLES`, `DISPUTE_ROLES`, `CLAIM_ROLES`); `owner_guard` on all ten single-resource reads that have an owning concession; every declared filter set matching §2.3; `created_at`-then-insertion-order listing; filter-before-paginate `total_count`; the derived payment-summary field list. `deductions.py`: `sequence_no` assignment, `raw_amount_cents` = points × 1,250, the `ISSUED` field set, the waterfall and pro-rata variants, the pinned four-step pricing chain, the withdrawal dispute-closure fields (`UPHELD`/`WITHDRAWN_BY_AUTHORITY`/`SYSTEM`), refer-back not consuming a round, resubmit incrementing by one, the three-round budget, adjudication's SoD and the five-row uphold cascade vs the inert reject. §5: all 40 ids and statuses match `errors.py` exactly.

Two dead branches noted but deliberately left alone: `calculate_compensation`'s null-`actual_service_commencement` path (unreachable, since `OPERATIONS` is only entered via `certify-service-commencement`, which sets it) — §3.11's existing "0 where null" sentence is harmless and matches the code; and `resubmit`'s `ERR_DISPUTE_ROUNDS_EXHAUSTED` guard (a `REFERRED_BACK` dispute can only hold `round_no` 1 or 2), which §3.6 already states for both operations.

---

## Pipeline complete — orchestrator final verification, 2026-09-03T13:36:00.000Z

- `workspace/PRD_COMPLETED.md`: 425 lines / 116,572 bytes; independently re-checked by the orchestrator — tail ends at the §5 table's final row (`ERR_NO_REFINANCING_GAIN | 422`), 2 `json` fences present, 30 headings, and `diff` against `PRD_FINALIZED.md` reports exactly 40 changed lines, so the three passes' 49 total edits are all present and the file was never truncated or clobbered.
- PRD lineage byte sizes: `PRD.md` 100,752 → `PRD_FINALIZED.md` 101,745 (+0.99%) → `PRD_COMPLETED.md` 116,572 (+14.6% over PRD.md). No file is byte-identical to its predecessor, so neither Step 8 nor Step 9 silently no-op'd.
- Test artifacts: `test_helpers/` (9 files) and `test_suite/` (conftest + 17 test modules, 126 tests) at the task-directory root.
- Green sweep still valid for the shipped code: the newest implementation source mtime is 12:31 (`db.py`, `routes/enforcement.py` — the Step 7 fixes); all eight `workspace/implementation/results.{1..8}.json` are stamped 12:36 and each reports 126/126. Steps 8 and 9 edited documentation only — no implementation file was touched after the passing sweep.
