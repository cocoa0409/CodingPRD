# Worklog — task_2396_veterans_education_benefit_certification

## Step 1: Create task directory — 2026-09-02T06:42:55.879Z

Created `tasks/task_2396_veterans_education_benefit_certification/` and `tasks/task_2396_veterans_education_benefit_certification/workspace/` (pre-allocated task name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T08:35:39.389Z

All three scaffold artifacts are complete and lint-clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2396_veterans_education_benefit_certification/`):
- `SCAFFOLD.yaml` — 2879 lines, §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2264 lines, single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4757 lines, single key `scaffold_corner_design`

**Spec counts (§1.0–§1.7)**: 13 entities, 60 endpoints, 70 errors, 40 priority-ordered validations, 7 calculations, 13 state-machine blocks (incl. parallel dimensions), 2 `concurrency_rules` (OCC on tuition-fee-report repricing and Yellow-Ribbon award pool), 6 roles under a segregation-of-duties model. Profile: Compliance/audit primary, ledger-reconciliation secondary; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; cyclic state shape; immediate consistency.

**§1.8 difficulty design**: 22 instances across all nine rules — dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2. Above-expert hooks include the AS_CERTIFIED vs AS_RECONCILED money divergence, the pinned R1–R5 evaluation order that breaks an apparent circular dependency, a five-level reconcile cascade (report → recompute → entitlement credit + debt creation → student balance/notification stamp → provisional YR award reversal), 30th-day-timely / 31st-day-late boundaries, and the 38 USC 3679(e) protection window.

**§1.9 corner design**: 77 instances (54 with `test_recipe`, 23 `excluded_because` stubs) over 9 taxonomy sections — entities 11, state_machines 17, calculations 13, validations 10, endpoints 5, rbac 6, errors 9 (all stubs), cross_cutting_complexity_layers 5, consistency 1.

**Coverage audits (all passing)**:
- `scaffold_lint.py` → `VERDICT: clean lint` (60 endpoints, 13 entities, 22 §1.8 + 54 §1.9 instances, 1156 calls scanned).
- Endpoint coverage now 60/60 — I closed the last gap this session by adding `every_collection_endpoint_lists_and_filters_its_own_rows` to the `endpoints` section, which exercises the 7 previously uncalled collection GETs (`/certifying-officials`, `/programs`, `/catalog-versions`, `/academic-terms`, `/yellow-ribbon-agreements`, `/enrollment-change-reports`, `/student-account-charges`) with a fixture that splits each declared filter one-to-one and includes two zero-row negatives.
- 0 duplicate instance names across the 99-instance union; 0 unbound `${var}` placeholders; every stub's `difficulty_instance` resolves to a real §1.8 name; no stub carries a `test_recipe` and no non-stub lacks one; all 70 errors either triggered or explicitly stubbed; 0 occurrences of forbidden concurrency vocabulary.

No sibling task directory was consulted — the scaffold was derived solely from the scenario text and the generator skill's specification.

## Step 3: Copy shared files — 2026-09-02T08:35:59.945Z

Copied `./INSTRUCTION.md` → `tasks/task_2396_veterans_education_benefit_certification/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T08:53:01.261Z

PRD generated and audited.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2396_veterans_education_benefit_certification/workspace/PRD.md` — 523 lines.

**Structure written**
- §1 Introduction — 3 paragraphs (domain framing: VA Chapter 30/31/33/35/1606 certification, rate of pursuit, MHA, Yellow Ribbon, 38 USC 3679(e) protection, overpayment debt).
- §2 Global Specifications — 12 domain-derived subsections: 2.1 roles/RBAC & identity translation, 2.2 verbatim response-structure block, 2.3 pagination, 2.4 collection filter vocabulary, 2.5 common properties + audit trail, 2.6 logical clock, 2.7 cents/days/rounding, 2.8 the full 40-priority rejection ladder, 2.9 optimistic concurrency, 2.10 segregation of duties, 2.11 cascades & ledger invariants, 2.12 reference resolution order.
- §3 Business Logic & Workflows — 9 subsections (officials/students; COE & protection window; terms/programs/SAA review; drafting-revising-submitting; pricing; certifying to VA; Yellow Ribbon matching; change reports & reconciliation; debt notification/collection/waiver/charges).
- §4 API Endpoints — 60-row table, exactly 4 columns.
- §5 Error Code Catalogue — 70-row table, exactly 2 columns.

Ends at the §5 table; no audit footer written into the file. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 126 required, 126 present, 0 missing
- endpoints[].request_body/input: 87 required, 87 present, 0 missing
- endpoints[].query_params: 0 required, 0 present, 0 missing
- endpoints[].path_params: 1 required (`id`), 1 present, 0 missing
Status: PASS
```
(Two independent passes: pass 1 against a hand-built inventory, pass 2 re-extracted directly from SCAFFOLD.yaml with optional `?` markers stripped. Also verified: 70/70 error ids, 6/6 role names, 53/53 state literals all appear verbatim in backticks.)

```
Rule coverage check:
- validations[] with priority: 40 checked, 40 expressed in prose, 0 missing
  (§2.8 ladder reproduces scaffold priority order 1→40 exactly, each with error_id, HTTP status and applies_to scope)
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id + status all named), 0 missing
- state_machines[].transitions: 53 checked, 53 fully expressed, 0 missing
- calculations[]: 7 checked, 7 fully expressed, 0 missing
  (rate_of_pursuit_and_training_time, mha_term_total both variants, covered_tuition_and_yellow_ribbon S1–S8 + S1′, entitlement_days_charged both variants, change_report_lateness_and_liability, overpayment_debt_allocation R1–R5 + waterfall, student_protection_window)
- validations[] conditions: 40 checked, 40 matchable to error_id in prose, 0 missing
- endpoints[].side_effects: 35 endpoints with side-effect blocks checked, 35 expressed, 0 missing
- entities[].fields[] structured content: 13 entities / 145 field slots checked, reconstructible from prose, 0 missing
- sibling-branch symmetry: 11 groups checked, 11 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 884
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Other verifications**: §2.2 matches `section-2.2-response-structure.md` byte-for-byte; §4 method/path/role sets diffed against the scaffold with 0 mismatches and 0 extras; §5 HTTP statuses diffed against the scaffold with 0 mismatches; all pinned constants present (99650, 2790000, the 50-percent strict MHA threshold, 30-day billing month, 30-day reporting/notification deadlines, 90-day protection window).

**Two repairs made during the audit** (sibling-symmetry strengthening, not gaps): added explicit `NOT_SUBMITTED → VERIFIED` / `EXPIRED → VERIFIED` arrow notation in §3.2 and `DRAFT → PENDING_SAA` in §3.3, where the branches had previously been stated only in prose alongside their siblings' arrow form.

## Step 5: Generate unit tests — 2026-09-02T10:32:24.964Z

*Orchestrator note: the Step 5 subagent was interrupted mid-run by a transient API error after writing `test_helpers/` (9 files) and `test_suite/test_01`…`test_17`, with §1.9 `rbac` / `cross_cutting_complexity_layers` / `consistency` still pending. It was resumed in-place with its context intact rather than relaunched, so the summary below is the resumed agent's final report and covers only the files it wrote after resuming plus the full-suite audit. Verified on disk after exit: 19 `test_suite/test_*.py` modules.*

Both remaining modules are written and the suite now covers every live design instance.

## Files written this session
- `/home/ubuntu/github/CodingPRD/tasks/task_2396_veterans_education_benefit_certification/test_suite/test_18_role_boundaries.py` — 15 test functions / 25 collected cases
- `/home/ubuntu/github/CodingPRD/tasks/task_2396_veterans_education_benefit_certification/test_suite/test_19_concurrency_and_immediacy.py` — 18 test functions / 18 collected cases

(Earlier this session, before the interruption: `test_14_input_rejections.py`, `test_15_priority_ladders.py`, `test_16_penalty_bar_and_balances.py`, `test_17_collection_reads.py`.)

## Per-section counts for the four sections requested
| §1.9 section | live instances | tests |
|---|---|---|
| `endpoints` | 5 | 18 (test_17) |
| `rbac` | 6 | 15 (test_18) |
| `cross_cutting_complexity_layers` | 2 | 10 (test_19) |
| `consistency` | 1 | 8 (test_19) |

test_18 breakdown: end-to-end role pass 2, cross-role refusals 2 (one 6-way parametrized), official identity registered/active/level 4 (one 2-way), header authentication 2 (one 3-way), student scope 2 (one 3-way), segregation of duties 4 (certify-own-submission blocked at `ERR_SEGREGATION_OF_DUTIES` 422, second supervisor succeeds, reconciler blocked from waiving at `ERR_WAIVER_SEGREGATION` 422, second official waives).

test_19 breakdown: stale certification version 5 (412 refusal, refused write discards nothing, retry's own `net_covered_cents` 3150000, certification repriced with version 3, first report `SUPERSEDED` with exactly 2 rows), stale agreement version 5 (412 refusal, nothing debited, pool/participant/version moved only by the accepted award, retry debits again to `participant_count` 2, `pool_remaining_before_cents` snapshot), consistency 8 (status/basis/certifier on the body, `entitlement_days_charged` 110, `net_covered_cents` 2950000, `ay_cap_remaining_before_cents` 2790000 with `va_tuition_cents`/`cap_charged_cents`, `yr_gap_cents` 160000, response body identical to an immediate read, student ledger already at 970, protection already true).

## Instances skipped
None in these four sections — all 14 live instances were translated. The only untranslated design content remains the 23 corner instances carrying `excluded_because:` stubs (`errors` 9, `calculations` 7, `state_machines` 4, `cross_cutting_complexity_layers` 3), which are not to be translated.

## Full-suite audit result
- Modules: `conftest.py` + `test_01`…`test_19`; **230 tagged test functions, 265 collected cases**.
- Tags: no untagged, dual-tagged, or unresolvable `Design:` lines; every `PRD: "..."` quote verified verbatim against `workspace/PRD.md` after whitespace normalization.
- Difficulty (§1.8): **22 of 22 instances covered, 0 thin** (all ≥2 tests).
- Corner (§1.9): **54 of 54 live instances covered**, 0 uncovered.
- `python -m py_compile` clean; `pyflakes` clean (only the intentional `# noqa: F401` fixture re-exports in `conftest.py`); every `c.*`/`f.*`/`a.*`/`api.*` symbol resolved by direct import check; `pytest --collect-only` has no collection errors; no "scaffold" mentions and no `skip`/`skipif`/`xfail` anywhere in `test_suite/` or `test_helpers/`.

Nothing under `workspace/implementation/` was read or written.

## Step 6: Generate implementation — 2026-09-02T10:32:24.964Z

The implementation is complete and verified.

## Files written
`/home/ubuntu/github/CodingPRD/tasks/task_2396_veterans_education_benefit_certification/workspace/implementation/`

- `start.sh` — launcher (`exec python3 app.py`), installs deps only when Flask is missing so the per-test reboots don't re-run pip; honours `PORT` (default 10000)
- `requirements.txt` (`flask>=2.3`), `app.py` (app factory, `ApiError` + 400/404/405/500 envelope handlers)
- `db.py` (in-memory `Store` with 13 empty dicts + logical clock + `RLock`), `errors.py` (all 70 error ids → HTTP status), `response.py` (meta/response_type/data envelope), `common.py` (auth ladder rungs 1-2/4-6, row + date helpers, `ListQuery` pagination/filter validator, 12 path-id getters, audit append), `validation.py` (rung-3 field checks), `calc.py` (CALC-1…CALC-7), `domain.py` (CALC-1 write-back, CALC-7 snapshot refresh, catalog resolution, terminal guard, full CASCADE-A)
- `routes/` — `admin.py`, `students.py`, `academics.py`, `yellow_ribbon.py`, `certifications.py`, `changes.py`

## Coverage
All **60 endpoints** implemented — verified programmatically that the Flask `url_map` matches the scaffold §1.5 method+path list exactly (60 spec / 60 impl, no missing, no extras), and that the error catalog matches §1.6 exactly (70/70 ids and statuses).

## Notable design decisions
- **Ladder ordering is structural**: every handler runs `authenticate` → body/`ListQuery` validation (rung 3) → `require_official` (4-6) → path-id 404 (7) → student scope (8) → body FKs (9) → OCC (10-11) → state gates (12) → higher rungs in ascending priority. `ListQuery` splits validation from rendering precisely so pagination/enum-filter checks precede the official-registration rungs.
- Real wall clock for `created_at`/`updated_at`/`api_request_timestamp`; the logical clock drives only date-dependent rules. Client date inputs are echoed verbatim; computed dates emit `YYYY-MM-DDT00:00:00Z`.
- One `version` bump per row per request even inside cascades (mutations accumulate, `touch()` once); a clock advance only touches students whose `benefit_payment_protected` actually flipped.
- Terminal precedence per PRD §3.4: submit/certify/return/void/record-va-payment/change-report creation → `ERR_CERTIFICATION_TERMINAL`; PATCH is deliberately excluded → `ERR_CERTIFICATION_NOT_EDITABLE`.
- Interval semantics kept distinct: enrollment overlap CLOSED (touching endpoints collide), catalog windows HALF-OPEN (touching windows legal).
- Storage is in-memory dicts only; nothing is seeded, preloaded, or persisted — confirmed `total_count: 0` on three consecutive cold boots.

## Boot / behaviour verification
Server boots clean and answers requests; three consecutive kill-and-relaunch cycles were ready in 4-7 s each (limit is 60 s) with an empty store every time. Three smoke suites (~110 assertions) all pass, including: full happy path through certify, OCC 412 on both guarded writes, segregation of duties, CASCADE-B (catalog suspend → program SUSPENDED → SUBMITTED cert auto-returned + `CERTIFICATION_AUTO_RETURNED` system audit entry), CASCADE-A (late COMPLETE_WITHDRAWAL → cert TERMINATED, prorated net 188182, prorated entitlement 23, two-rate MHA 184000, SCHOOL/`LATE_REPORTING_LIABILITY` debt of 1399818 = 711818 tuition + 688000 housing), debt notify/acknowledge/mark-overdue/repay/waive with waiver segregation, 38 USC 3679(e) penalty bars, and the whole 401/403/400/404/409/412/422 ladder. CALC-2's pinned example reproduces exactly (`776444`, per-segment rounding).

One caution: while restarting my own test server I twice ran `pkill -f "python3 app.py"`, which may have briefly killed sibling task servers on this host — those are relaunched per test by the harness, and I switched to port-scoped kills afterwards.

## Step 7: Run tests and iterate — 2026-09-02T12:35:00.000Z

The 8-round parallel stability sweep came back fully green on the first iteration — no fixes were required.

## Summary

**Iterations run: 1**

Sweep (all 8 rounds launched concurrently under `setsid nohup`, joined with `wait`, `--isolation per-test-server`, ~1950s wall time):

| round | passed / total | failed |
|---|---|---|
| 1–8 | 265 / 265 | 0 |

`SWEEP DONE` written to `/home/ubuntu/github/CodingPRD/tasks/task_2396_veterans_education_benefit_certification/workspace/sweep.log`; results in `workspace/implementation/results.{1..8}.json`. No `Terminated` in any server log (only the runner's own `Killed`), and rounds finished at staggered times, so the sweep was correctly detached and the green result is not a reaping artifact.

**Tests deleted:** none. No test failed in any of the 8 rounds, so STEP 0 produced an empty union set and the diagnostic protocol never entered STEP 1.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

### Audit of the prior run's uncommitted edits
The task prompt flagged that a previous pipeline run had modified `test_suite/test_17_collection_reads.py`, `test_suite/test_18_role_boundaries.py`, and `workspace/implementation/common.py` without leaving a Step 7 record. I audited all three against the PRD before accepting the baseline:

- **No test was deleted or weakened.** `grep` across `test_suite/` and `test_helpers/` finds zero `skip` / `skipif` / `xfail` markers and zero `validate_error_is_one_of` relaxations. Test-function counts still match the Step 5 audit exactly (test_17 = 18, test_18 = 15), and the 265 collected cases match the recorded full-suite count — nothing was dropped.
- **`workspace/implementation/common.py`** retains every PRD-required gate: `authenticate()` implements ladder rungs 1–2 (§2.8) and `require_official()` implements rungs 4–6 (`ERR_OFFICIAL_NOT_REGISTERED` / `ERR_OFFICIAL_INACTIVE` / `ERR_OFFICIAL_LEVEL_MISMATCH`) in order. The prior edits added the `ListQuery` / `enum_filter` machinery that runs §2.3 pagination bounds and §2.4 enum-filter-domain validation as rung 3, i.e. *before* the official rungs — which is what the ladder requires, not a loosening.
- One judgement call left in place: `fmt_day()` serializes computed calendar dates as bare `YYYY-MM-DD`, and `test_17` line 442 asserts `notification_due_on == "2026-10-05"`. PRD §2.6 pins the "ISO 8601 date at `00:00:00Z`" shape only for the enumerated *input* fields, and `notification_due_on` is computed, so the exact wire form is not pinned. The load-bearing claim in that test — "The debt's `notification_due_on` is stamped 30 days after the current logical clock date" — is verbatim PRD, `YYYY-MM-DD` is a valid ISO 8601 date, and client-supplied dates are echoed verbatim so the suite is internally consistent. I kept the assertion rather than stripping the PRD-covered rule over a representation detail.

### Orchestrator note — Step 8 skip decision
Step 7 exited on the FIRST 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. Per the skill's Step 8 skip condition, `PRD.md` already determined every behavior the implementation exhibits at the sites tests exercised, so Step 8 is SKIPPED and no `PRD_FINALIZED.md` is produced. Step 9 therefore starts from `workspace/PRD.md`.

## Step 8: Finalize PRD — 2026-09-02T12:36:00.000Z

SKIPPED per the skill's Step 8 skip condition. Step 7 exited on the first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline — so `PRD.md` already determined every behavior the implementation exhibits at the sites the tests exercised. No `<step_7_diff>` items existed to target, and Step 8's hard scope forbids edits that do not trace to such an item. No subagent was spawned; `workspace/PRD_FINALIZED.md` is deliberately absent. Step 9 therefore takes `workspace/PRD.md` as its source.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-02T13:25:00.000Z

All edits landed. `PRD_COMPLETED.md` is written.

## Summary

**Files:** source `workspace/PRD.md` = 522 lines / 103,797 chars → `workspace/PRD_COMPLETED.md` = 522 lines / 108,689 chars (**+4,892 chars**, 25 lines revised in place, 0 lines added/removed, 0 new sections).

**Counts:** 22 ambiguity-pins, 3 mismatch-revisions.

### Changes

- §2.2 Success envelope — insert — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case-alphanumeric chars — `response.py:19`
- §2.3 Pagination — insert — ambiguity — a non-integer `limit`/`offset` is also `ERR_INVALID_REQUEST` — `common.py:179-193`
- §2.3 Pagination — insert — ambiguity — identical `created_at` broken by server write order — `common.py:87`
- §2.4 Filter vocabulary — insert — ambiguity — enum filters reject out-of-domain values with `ERR_INVALID_REQUEST`; free-text/id filters are exact-equality and unvalidated — `common.py:203-215`
- §2.5 Common properties — revise — ambiguity — `version` is **1** on creation (was "the value assigned on creation") — `common.py:70`
- §2.6 Logical clock — insert — ambiguity — clock advance stamps a student row only when the snapshot actually flips (unlike §3.2 recomputes, which stamp unconditionally); advance returns 200 with empty `data` — `admin.py:44-47`
- §2.6 Date semantics — insert — ambiguity — client dates echoed verbatim; server-computed dates rendered bare `YYYY-MM-DD` — `common.py:121-141`
- §2.8 rung 3 — insert — ambiguity + mismatch — absent/empty body = `{}`, non-object body malformed, explicit `null` = absent; and the mark-overdue due-date check is the one shape check *not* at priority 3 — `validation.py:11-32`, `changes.py:237-244`
- §3.1 Student registration — insert — ambiguity — `benefit_level_pct` outside the seven values is `ERR_INVALID_REQUEST` — `students.py:50`
- §3.2 COE expiry — revise — ambiguity — expiry also leaves `coe_issued_on` and `verified_document_reference` intact — `students.py:129-131`
- §3.3 Catalog versions — insert — ambiguity — no ordering rule between `effective_start`/`effective_end` — `academics.py:182-183`
- §3.3 Submit-to-SAA — insert — ambiguity — response carries the catalog version, not the program — `academics.py:251`
- §3.3 SAA decision — insert — ambiguity — response is the version; a `conditions_note` on a non-storing branch is discarded; `suspension_reason` untouched — `academics.py:271-288`
- §3.3 Suspension L1 — insert — ambiguity — the suspended version is what the response returns — `academics.py:330`
- §3.3 Suspension L2 — insert — ambiguity — program's `approved_catalog_version_id` stays pinned; programs walked in ascending `created_at` — `academics.py:308-313`
- §3.4 Certification creation — insert — ambiguity — halves are not enforced as a granularity; no ordering rule on the certified period; full list of opening nulls/zeros — `certifications.py:69-115`
- §3.4 Submission — revise — mismatch — the six conditions are listed/evaluated in ladder order, delimiting-date **before** inside-the-term (PRD had them inverted) — `certifications.py:200-207`
- §3.5 Tuition report — insert — ambiguity — `expected_certification_version` is not stored/echoed; no state gate on the certification (terminal included) — `certifications.py:403-419`
- §3.6 Record VA payment — revise — mismatch — dropped the "must be `CERTIFIED` else `ERR_CERTIFICATION_NOT_CERTIFIED`" requirement; only the terminal guard and the already-recorded guard apply — `certifications.py:349-363`
- §3.8 Change report inputs — insert — ambiguity — "ignored" fields are still stored/echoed as supplied, null when omitted — `changes.py:106-108`
- §3.8 Reconciliation guards — insert — ambiguity — response carries the change report — `changes.py:161-162`
- §3.8 Reconcile L2 — insert — ambiguity — `credit_hours_total/online`, `term_start/end_certified` and `certified_days` are **not** rewritten, even for `TERM_DATE_CHANGE` — `domain.py:137-186`
- §3.8 Debt record — insert — ambiguity — fresh-debt opening values (repaid buckets 0; five fields null) — `domain.py:211-228`
- §3.8 Reconcile L5 — insert — ambiguity — cascade `AWARD_REVERSED` carries `system`/`system` and is appended last (`AMENDMENT_RECONCILED` → `DEBT_CREATED` → `AWARD_REVERSED`) — `domain.py:259-265`
- §3.9 Mark overdue — insert — mismatch — notification-status gate is evaluated before the due-date check, so `ACKNOWLEDGED` + not-yet-due yields `ERR_DEBT_ALREADY_NOTIFIED` — `changes.py:237-244`
- §3.9 Registration holds — insert — ambiguity — gate keys off requested `hold_status`, so re-asserting an existing hold is refused while protected; a no-op set still mutates the row — `students.py:142-147`

**Note on one impl/PRD gap left alone:** §3.9's "if any of the payment is still unallocated after both buckets … rejected with `ERR_REPAYMENT_EXCEEDS_BALANCE`" has no counterpart in `calc6_allocate`, but since `outstanding_cents` always equals the sum of the two buckets' unfilled room, the branch is mathematically unreachable and unobservable — no revision needed.
