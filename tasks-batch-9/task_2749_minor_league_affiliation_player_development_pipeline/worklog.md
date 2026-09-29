# Worklog — task_2749_minor_league_affiliation_player_development_pipeline

## Step 1: Create task directory — 2026-09-04T15:44:12.867Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2749_minor_league_affiliation_player_development_pipeline` and its `workspace/` subdirectory. Index 2749 was pre-assigned by the orchestrating command; no index scan was performed.

## Step 2: Generate scaffold — 2026-09-04T17:09:00.000Z

All three scaffold artifacts for task 2749 are complete and lint-clean.

Final lint output (verbatim):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    41
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     65
  Calls scanned (§1.8+§1.9):  1072

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files

| Path | Lines | Bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 2963 | 145 KB |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1805 | 110 KB |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 5293 | 317 KB |

`SCAFFOLD.yaml` carries only §1.0–§1.7 (verified: neither `scaffold_difficulty_design` nor `scaffold_corner_design` present); the other two files each have exactly one top-level key.

## Design

**14 entities:** Affiliate, AffiliationAgreement, FacilityStandardReview, StaffMember, StaffAllocation (junction), Player, MedicalClearance, PlayerAssignment (junction, self-referential via `superseded_assignment_id`), DevelopmentPlan, WorkloadLog (immutable event), OptionYearRecord, TransactionReport, SigningPool, InternationalSigning.

**41 endpoints** across affiliates/agreements/facility-reviews, staff-members/staff-allocations, players/medical-clearances, assignments/development-plans/workload-logs/option-years/transaction-reports, signing-pools/international-signings, plus `POST /_clock/set_current_utc`. **57 error codes, 37 validations** on a pinned priority ladder (1→90), **11 state machines, 9 calculations** (weighted workload index with a 14-day rolling window, waterfall expense allocation with per-category sub-caps, tiered signing-pool overage tax with an order-sensitive TIER_3 forfeit, promotion readiness, option-year charge, facility posture/deficiency bands, late-filing fee tiers, roster/reserve aggregation), **5 roles** (FarmDirector, MedicalDirector, ComplianceOfficer, AffiliateOperator with `entity_backed:Affiliate` identity, InternationalScout), 3 OCC rules, `consistency_model: immediate`.

**§1.8:** 9 difficulty rule_ids × 2 instances = **18**.

**§1.9:** **79 instances** across all nine guide sections (65 full test recipes + 14 `excluded_because` stubs, each citing a real §1.8 instance name): entities 12, state_machines 13, calculations 13, validations 9, endpoints 5, errors 14, rbac 4, cross_cutting_complexity_layers 7, consistency_model 2.

Verified beyond the linter: all 97 instance names unique across §1.8 ∪ §1.9; every one of the 57 catalog error codes is referenced by at least one instance; every one of the 41 endpoints is called by at least one instance; no stub carries a `test_recipe`; the difficulty directive line appears in zero files; only `§` and em-dash are non-ASCII. Two defects found and fixed during the pass: an unquoted `$.data[0].id` inside a flow mapping (PyYAML flow-mapping restriction) and a payload key `facility_upkeep_expense_cents` that §1.5 declares as `upkeep_expense_cents`.

Orchestrator verification: all three files present, non-trivial (2963/1805/5293 lines); `grep -rn "harder than expert"` over the task dir returned no hits, so the difficulty directive did not leak.

## Step 3: Copy shared files — 2026-09-04T17:10:03.905Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T17:28:00.000Z

The PRD is complete and verified.

## Deliverable

**Path:** `workspace/PRD.md`
**Line count:** 460 lines (104,951 bytes)
**Built:** 10 chunked `cat >>` appends + 2 targeted `Edit`s — no single giant Write, so no 64k truncation risk.

**Section list (27 headings):**
- `# Minor League Affiliation & Player Development API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Role-Based Access Control · 2.2 API Response Structure (verbatim block) · 2.3 Pagination · 2.4 Resource Identity, Audit Fields and Mutation Semantics · 2.5 The Logical League Clock · 2.6 Validation Order · 2.7 Optimistic Concurrency on Shared Parents · 2.8 Money, Counts and Rounding Discipline · 2.9 Facility Standing and the Affiliate Posture Gate · 2.10 Cascade and Reconciliation Discipline · 2.11 Curriculum Consistency · 2.12 Segregation of Duties in League Filings (12 subsections, within the 8–12 range)
- `## 3. Business Logic & Workflows` — 3.1 Standing Up an Affiliate Club and Its League Standards · 3.2 The Player Development License · 3.3 Expense Allocation and Settlement · 3.4 Allocating Coaching and Support Staff · 3.5 Players, Their Two Independent Standings, and Medical Clearance · 3.6 Assignment, Option Years and Roster Capacity · 3.7 Development Plans, Workload Governance and Promotion Readiness · 3.8 Reporting Player Movement to the League Office · 3.9 International Signing Pool and Academy Operations (9 subsections, within the 5–9 range)
- `## 4. Endpoint Definitions` — intro paragraph plus a 4-column table (Method / Path / Description / Authorized Role(s)), **41 rows**, no bodies or side effects
- `## 5. Error Code Catalogue` — 2-column table (Error ID / HTTP Status Code), **57 rows**

**Tail boundary confirmed:** the last non-empty line is `| \`ERR_MEAL_STIPEND_BELOW_MINIMUM\` | 422 |` — the final row of the completed §5 table. The document ends at a real section boundary, not mid-sentence, with no audit footer. `workspace/` contains only `PRD.md` and the pre-existing `INSTRUCTION.md`; no sibling report files were created.

## Hard Contract Reports

**CONTRACT 1 — FIELD-NAME COVERAGE: PASS** (two independent passes run)
- Entity field names checked: **148** across 13 entities — **0 missing**
- Endpoint identifiers checked: **146** slots (`request_body` / `input` / `query_params` / `path_params`), **81 unique** — **0 missing**
- All enum literal values across every entity field: **0 missing**
- Pass 2 re-ran after the §3.1 edit with identical results: 148/0, 146/0

**CONTRACT 2 — RULE COVERAGE: PASS**
- All **57** error identifiers appear in §1–§3 prose at the rule that raises them (not merely in the §5 table)
- All **61** state transitions across 11 state machines narrated; every `from`/`to` state present; all **28** distinct disposition actions present
- **37** validations narrated in ascending-priority order in §2.6 with error id and HTTP status, across **31** distinct `applies_to` scopes
- All **9** calculations translated to operator-free prose (including the dual-variant expense waterfall and the ordering-load-bearing 4-step signing-pool charge); all **3** `concurrency_rules` and all **5** roles narrated
- All 18 `global_constants` covered by name or value, including the per-level `LEVEL_ROSTER_LIMIT` map (28/28/30/30/35/40)
- Sibling-branch symmetry honoured with equal prose density (both waiver entry states, both termination paths, all three assignment-revoke entry states, both medical-restriction paths)
- Scans for fuzzy words (`approximately`, `roughly`, `conservatively`, …) and for pseudocode operators inside backticks: **0 hits**

**CONTRACT 3 — §3 PATH PURITY: PASS**
- **284** backticked tokens scanned in §3 — **0 violations**: no token starts with `/`, no bare HTTP method, no method+path combination. Paths appear only in §2.7 (SKILL-sanctioned OCC block) and the §4 table.

## Two findings worth flagging

1. **One genuine coverage gap was caught and fixed by Contract 2**, not by review: `ERR_INVALID_REVIEW_STATE` appeared only in the §5 table, never in prose — §3.1's inspection narrative had the cycle bound and the waiver rule but no catch-all invalid-transition sentence. Added at line 208 with three concrete refused examples plus the `version` increment.

2. **My first Contract 1 script produced 121/148 false "missing" results.** Cause: `re.findall` over single backticks mis-pairs once the document contains triple-backtick fences (the verbatim §2.2 JSON blocks), which shifts every subsequent pairing. Any future contract checker must strip fenced regions before extracting single-tick spans — otherwise it reports catastrophic phantom failures on a correct PRD.

The prohibition held throughout: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

Orchestrator truncation check (the known doc-generator failure mode): `wc -l` = 460; `tail -12` ends on the final `ERR_MEAL_STIPEND_BELOW_MINIMUM` row of the §5 table — a real section boundary, not mid-sentence. No regeneration needed. `grep -c "harder than expert" PRD.md` = 0, so the difficulty directive did not reach the PRD.

## Step 5: Generate unit tests — 2026-09-04T18:46:00.000Z

Generation is complete for task 2749.

## Output locations (task root, nothing under `workspace/`)

**Stage 1 — `test_helpers/` (2309 lines)**
| file | lines |
|---|---|
| `__init__.py` | 120 |
| `api_client.py` | 164 |
| `api_errors.py` | 130 |
| `assertions.py` | 356 |
| `constants.py` | 196 |
| `factories.py` | 192 |
| `fixtures.py` | 673 |
| `test_users.py` | 78 |
| `types.py` | 400 |

**Stage 2 — `test_suite/` (7967 lines, 102 tests)**

Queue A (§1.8, 4 tests each): `test_01_dual_variant_calc.py` 286, `test_02_combinatorial_formula.py` 222, `test_03_non_linear_state_machine.py` 282, `test_04_transitive_cascade.py` 318, `test_05_priority_pair_validation_conflict.py` 263, `test_06_boundary_precision_check.py` 234, `test_07_cross_entity_state_dependency.py` 272, `test_08_resource_temporal_overlap.py` 328, `test_09_compensating_invariant.py` 299 — **36 tests**.

Queue B (§1.9): `test_10_corner_entities.py` 528/12, `test_11_corner_state_machines.py` 658/8, `test_12_corner_calculations.py` 764/9, `test_13_corner_validations.py` 562/8, `test_14_corner_endpoints.py` 515/5, `test_15_corner_errors.py` 1131/13, `test_16_corner_rbac.py` 431/4, `test_17_corner_complexity_layers.py` 619/5, `test_18_corner_consistency_model.py` 201/2 — **66 tests**. Plus `conftest.py` 54.

## Verification performed

- **Coverage audit (scripted against both design yamls):** all 18 non-stub §1.8 instances have exactly 2 tests each; all 65 non-stub §1.9 instances have >=1 test. No missing instances.
- **Tag audit:** every one of the 102 tests carries exactly one `Design:` line as its docstring's last line; 0 untagged, 0 dual-tagged, 0 orphan tags, 0 tags pointing at an `excluded_because:` stub.
- **Stub cross-reference:** all 14 corner stubs cite a real §1.8 instance by name, each of which is itself covered by 2 tests.
- **PRD-citation fidelity (AST sweep over all 18 files):** every quoted span is verbatim-greppable against `workspace/PRD.md` after whitespace flattening. The single remaining regex hit is an artifact (the prose span *between* two adjacent citations in `test_15`), not a citation.
- **Scaffold-leak scan:** zero occurrences of "scaffold" or scaffold section numbers in any comment or docstring.
- **Syntax/lint:** `python3 -m py_compile` clean over all 28 files; `pyflakes` clean over `test_suite/` (only expected F401 re-export noise in `test_helpers/__init__.py`, which is `# noqa`-annotated).
- **Collection:** `PYTHONPATH=. python3 -m pytest test_suite --collect-only -q` -> **102 tests collected**, no import errors.
- **Paths:** `find` confirms `test_helpers/` and `test_suite/` exist only at the task root; `workspace/` holds only `INSTRUCTION.md`, `PRD.md`, `implementation/`. `worklog.md` and `workspace/implementation/` untouched. `__pycache__`/`.pytest_cache` cleaned up.

## Instances skipped

**None.** Every non-stub instance in both design indices passed the PRD-first two-condition filter and was translated. The 14 `excluded_because:` corner stubs emit no tests by design.

One PRD-first correction worth flagging: the `submit_response_already_carries_the_provisional_settlement_figures` recipe asserts `final_club_obligation_cents == 0` before settlement, but PRD 3.2 states a draft carries `final_club_obligation_cents` **null**. The test asserts `is None`, quoting that sentence — the design's figure would have contradicted the contract.

## Step 6: Generate implementation — 2026-09-04T18:46:00.000Z

Implementation complete.

## Deliverable
`workspace/implementation/`

**Launcher / deps**
- `start.sh` (10 lines, executable) — guarded `pip install` (skipped when Flask imports), `exec python3 app.py`
- `requirements.txt` (1) — `flask>=2.0`
- `app.py` (66) — blueprint registration, `before_request` -> `store.begin_request()`, ApiError/HTTPException/Exception handlers that call `store.rollback_request()` (failed requests write nothing), `app.run(host="0.0.0.0", port=int(os.environ["PORT"] or 10000), threaded=False, use_reloader=False)`

**Core modules** — `config.py` (173), `errors.py` (86, all 57 error IDs + statuses), `store.py` (219, 14 in-memory dicts, logical clock defaulting to `2026-08-01T00:00:00.000Z`, snapshot-diff version/`updated_at` machinery), `envelope.py` (89, `meta`/`response_type`/`data` + Decimal-scale-preserving JSON), `serialize.py` (154), `validate.py` (171), `auth.py` (58), `calc.py` (177), `derive.py` (369, `reconcile_all()`), `common.py` (77), `flows.py` (150, cascades)

**Routes** (`routes/`, 1333 lines) — `affiliates.py` 79, `agreements.py` 184, `reviews.py` 125, `staff.py` 186, `players.py` 183, `assignments.py` 297, `plans.py` 197, `reports.py` 70, `signings.py` 189, `clock.py` 22. Total codebase 3321 lines.

## Endpoints
**41 routes, an exact set-match against the PRD §4 endpoint table** (diffed programmatically: zero missing, zero extra).

## Verification
- `python3 -m py_compile` clean over all 22 `.py` files.
- Fresh `bash start.sh` (PORT=17493) booted in <3 s, bound `0.0.0.0`, empty store, clock at the `2026-08-01T00:00:00.000Z` default. Servers killed by the specific pid found on their own port only.
- End-to-end smoke coverage: auth 401/role 403, affiliate + licence draft->SUBMIT->ACTIVATE->SETTLE, facility inspection MAJOR->remediation->CLOSE with posture FROZEN->OPEN, staff member/allocation activation with FTE roll-up, player + clearance ISSUE, assignment create (OCC) -> ACTIVATE with option-year charge + PENDING report, development plan ACTIVATE/RECORD_PROGRESS, workload logs, report FILE/SOD-403/LEAGUE_REJECT/REFILE, signing pool + international signing APPROVE/VOID, agreement SUSPEND/REINSTATE/RESUME and TERMINATE cascade.
- Arithmetic spot-checks matched hand computation: provisional obligation 802500 (per-line rounding, single drained bucket), final 340962 with overflow 461538 (pro-rata sub-caps / 2.60), overage tax 475000 on a 600000 overage with `tier3_breach` false -> pool `HARD_CAPPED`, then VOID restoring `OPEN`/`remaining_cents` 600000, deficiency due date `review_date`+30.
- Rollback confirmed: a refused workload log (422 `ERR_WORKLOAD_CEILING_EXCEEDED`) left the log unpersisted and the player's `version` unchanged.

Two small fixes made this session: `store.parse_iso` timezone normalisation, and a new `derive.signings_of_academy()` helper for the `ERR_ACADEMY_HOUSING_FULL` bed count. No seeding, no `float()`, and `test_suite/`, `test_helpers/`, the difficulty/corner scaffold files and `worklog.md` were never read or written.

Orchestrator note: Steps 5 and 6 were launched concurrently in a single assistant message, so the implementation generator had physical isolation from `test_suite/` (the directory did not exist at its spawn time). Post-run layout check confirmed `test_helpers/` (9 files) and `test_suite/` (19 files) live at the task root with no stray copies under `workspace/`.

## Step 7: Run tests and iterate — 2026-09-04T19:00:00.000Z

Clean. No orphaned servers, no stray directories, `worklog.md` untouched.

## Summary

**Iterations run:** 2 (each a full 8-round parallel sweep under `setsid`).

- Iteration 1: 100/102 passing in all 8 rounds — 2 deterministic failures (union across rounds, no flakiness).
- Iteration 2: **102/102 passing in all 8 rounds.**

**Tests deleted:** none. Both failures passed STEP 1a/1b (PRD verbatim-covers and uniquely determines the rule), and both resolved at STEP 2 as test bugs.

**Fixes applied to `test_suite/`:**

1. `test_suite/test_16_corner_rbac.py:106` — `test_all_five_roles_carry_out_the_operations_the_contract_reserves_to_them` passed `cleared_workload_ceiling_index="25.00"` as a JSON **string**. PRD 2.6 check 8 requires "every numeric field lies inside its declared range", and the field is a numeric workload index (PRD 2.8/3.5/3.7), so the implementation correctly returned `ERR_INVALID_REQUEST`. Changed to the number `25.00`.
2. `test_suite/test_16_corner_rbac.py:188` and `test_suite/test_15_corner_errors.py:716` — same numeric-as-string bug on `cleared_workload_ceiling_index`. These two were *latently* wrong: their assertions expect `ERR_ROLE_NOT_PERMITTED` (403) and `ERR_MEDICAL_CLEARANCE_NOT_FOUND` (404), which PRD 2.6 short-circuits at checks 3 and 7 *before* the body-shape check 8, so they passed accidentally. Fixed to numbers so those rungs are genuinely isolated rather than accidentally correct.
3. `test_suite/test_14_corner_endpoints.py` — `test_the_player_listing_filters_on_each_derived_standing_independently` asserted `roster_status == "RESERVE_LIST"` for a freshly-registered player whose clearance was **denied**. PRD 3.5's roster state-machine enumeration says verbatim: *"And a player moves `RESERVE_LIST` -> `RESTRICTED` when any clearance for them is denied, with no further side effect."* The test had mis-applied the companion sentence (*"a denial restricts the medical dimension without touching `roster_status` and without disturbing any active assignment"*), which is scoped to the roster-**ACTIVE** player — that case is already covered by the separately-passing `test_a_denial_restricts_medical_standing_without_disturbing_the_active_assignment`. Corrected the assertion to `RESTRICTED` and rewrote the docstring citation to quote the governing sentence and note which sentence governs the ACTIVE case.

**Fixes applied to `test_helpers/`:** none needed — `factories.clearance_issue_payload` and `fixtures.issue_clearance` already emitted the ceiling as a JSON number; only the three inline call sites in `test_suite/` were wrong.

**Fixes applied to `implementation/`:** none. Both failures were test-side. Notably `routes/players.py` (clearance `DENY` branch, lines 159-165) already implements the exact PRD reading that reconciles the two PRD sentences — it moves `RESERVE_LIST` -> `RESTRICTED` while leaving a roster-`ACTIVE` player untouched — so no implementation check was weakened.

**Infrastructure note worth passing on:** on this host `setsid nohup bash -c '... & done; wait'` returns to the caller *immediately* (setsid forks and the parent exits) while the 8 rounds continue detached under PID 1. The first sweep therefore looked reaped — `SWEEP_DONE` echoed at ~11% progress with zero `results.*.json` — when it was in fact still running fine. Anyone joining this sweep shape must poll for all 8 `results.$i.json` files rather than trusting the launcher's exit, or they will misdiagnose a healthy sweep as reaped.

Orchestrator independent verification (per the known failure mode where a Step 7 agent reports a clean sweep with no artifacts on disk): all 8 `workspace/implementation/results.{1..8}.json` exist, timestamped 18:58, each reporting `passed 102 / total 102 / failed 0`. Confirmed genuinely green.

Step 8 skip decision: NOT skipped. The skip condition requires 0 deletions AND 0 test_suite/ fixes AND 0 test_helpers/ fixes AND 0 implementation/ fixes. Step 7 ran a second iteration and applied 3 `test_suite/` fixes, so a Step 8 pass runs — though with 0 `implementation/` fixes, the expected Step 8 outcome is few or no PRD edits (the numeric-string fixes are pure test bugs; the roster-status fix points at a genuine PRD readability tension between two adjacent §3.5 sentences, which is the one candidate worth pinning).

## Step 8: Finalize PRD — 2026-09-04T19:05:00.000Z

Done. Both edits applied to `PRD_FINALIZED.md`.

## Line counts
- `PRD.md`: 460 lines / `PRD_FINALIZED.md`: 460 lines — 0% line delta (both edits are in-line revisions of existing sentences; +2 clauses, no new sections). File still ends at the real final boundary, the last row of the Section 5 error catalogue (`ERR_MEAL_STIPEND_BELOW_MINIMUM | 422`).

## Changes
- **§2.6 check 8** — revise — "every numeric field lies inside its declared range" -> "every numeric field **arrives as a JSON number rather than as a string and** lies inside its declared range" — `implementation/validate.py:63-100` (`int_field` / `dec_field` both reject non-numeric JSON types with `ERR_INVALID_REQUEST`).
- **§3.5 (clearance disposition paragraph)** — insert — one sentence declaring `cleared_workload_ceiling_index`'s body shape: optional for every action, must be a JSON number (not a string), zero or greater, carried at two decimal places, and **not** subject to the `25.00` cap that bounds an assignment's own `workload_ceiling_index`; otherwise `ERR_INVALID_REQUEST` under check 8 — `implementation/routes/players.py:123-124`.

No edit was made for Step 7 item 3 (denial -> `RESTRICTED` roster move): PRD §3.5 already states that rule verbatim, and `routes/players.py:159-165` implements exactly it (moves only a `RESERVE_LIST` player to `RESTRICTED`, leaves an `ACTIVE` player's roster standing alone). That was a pure test bug.

## Per-edit pre-edit search log

**Edit 1 — §2.6 check 8**
- (a) Subject: type strictness of numeric request-body fields system-wide.
- (b) Paths enumerated: `validate.py` `int_field` (rejects `bool` and non-`int`), `dec_field` (rejects `bool`, non-`int`/`float`), plus a repo-wide sweep for numeric reads that bypass validation — `grep -rn "body\.get\|body\[" implementation --include=*.py` returns only `auth.py:53` (`action`, a string). So every numeric body field on every endpoint (affiliate `roster_limit`/`reserve_slots`/`housing_beds`/`meal_stipend_cents_per_day`, agreement expense/cap fields, review `score`, allocation `fte_pct`, player `service_days_accrued`, assignment `workload_ceiling_index`/`expected_player_version`, plan `workload_limit_weekly_index`/`completed_module_count`, workload-log measures, pool `season_year`/`base_pool_cents`/`trade_adjustment_cents`, signing `bonus_cents`/`expected_pool_version`, allocation `expected_affiliate_version`) funnels through those two helpers.
- (c) Adjustment: phrased as "JSON number rather than as a string" only — deliberately silent on int-vs-float strictness (`int_field` also rejects `5.0`, `dec_field` accepts ints), so the clause makes no claim any enumerated path contradicts.

**Edit 2 — §3.5 clearance disposition**
- (a) Subject: the `cleared_workload_ceiling_index` field — its accepted shape, range, scale, optionality, and downstream use.
- (b) Paths enumerated and read: `routes/players.py:95` (initialised null at request creation), `:123-124` (validated for **all** actions before the state check — `lo=0` inclusive, **no** `hi`, `places=2`, `required=False`, `default=None`), `:151` (written only on the `ISSUE` branch, possibly null); `serialize.py:69` (`CLEARANCE_FIELDS`) with `envelope.py:_prep`/`dump` (Decimals emitted as JSON numbers at their exact declared scale, never strings); `derive.py:150-157` `effective_ceiling` (consulted only when non-null, min against the assignment ceiling); `routes/plans.py:181` (the `ERR_WORKLOAD_CEILING_EXCEEDED` gate, the only consumer); parallel numeric-ceiling inputs `routes/assignments.py:119-121` (`workload_ceiling_index`: exclusive `>0`, `hi=25.00`) and the plan's `workload_limit_weekly_index`, whose ranges PRD already declares; `auth.py:41-58` to confirm an absent/unknown `action` also yields `ERR_INVALID_REQUEST`, so the new sentence's error claim cannot collide with a different code.
- (c) Adjustments made: (i) scoped the sentence to "a clearance disposition request ... whatever the action requested" rather than to issuing alone, because validation runs pre-branch and also fires on `DENY`/`REVOKE`; (ii) used "zero or greater" (inclusive), matching `lo=0`, not the exclusive `>0.00` of the assignment field; (iii) explicitly stated it is **not** held to the `25.00` bound, so no reader infers the assignment ceiling's cap — impl passes no `hi`; (iv) wrote "carried at two decimal places" with **no** rounding mode, since `dec_field` quantizes with Decimal's default half-even and PRD §2.8's global half-up rule does not list this field — naming a mode would have been a false universal.

Orchestrator verification: `cmp` confirms `PRD_FINALIZED.md` is NOT byte-identical to `PRD.md`; the diff shows exactly the two claimed in-line revisions at lines 111 and 264, both 460 lines, and the tail still ends on the final `ERR_MEAL_STIPEND_BELOW_MINIMUM` row.

## Step 9: Complete PRD — 2026-09-04T19:30:00.000Z

Orchestrator decision (recorded per the AUTONOMY directive): Step 9 was run as **three sequential module-partitioned passes** over one shared `PRD_COMPLETED.md`, rather than one monolithic scan. Rationale: a single subagent asked to walk a 3321-line, 22-module implementation against a 460-line PRD reliably under-scans and can return a file byte-identical to its input. Pass 1 owned the `cp` and the cross-cutting core (app/config/errors/store/envelope/serialize/validate/auth/common/clock); Pass 2 owned the club side (affiliates/agreements/reviews/staff/flows + the expense-waterfall and facility-band parts of calc/derive); Pass 3 owned the player side (players/assignments/plans/reports/signings + workload/promotion/option-year/signing-pool parts of calc/derive). Passes 2 and 3 were explicitly forbidden from copying the file so neither could wipe an earlier pass.

### Pass 1 — core / cross-cutting modules

`PRD_COMPLETED.md` created from `PRD_FINALIZED.md` (Step 0 copy done exactly once) and edited with 17 targeted `Edit` calls — no whole-file rewrite. Source 460 lines / 105,493 chars -> 469 lines / 112,169 chars (+9 lines, +6,676 chars). **15 ambiguity-pins, 3 mismatch-revisions.**

- §2.1 — revise — mismatch — header presence now covers whitespace-only values, and role matching is stated as exact/case-sensitive — `auth.py:11-14`
- §2.2 — revise — ambiguity — `api_request_id` pinned as `req_` + exactly 20 upper-case hex chars (24 total) — `store.py:60-62`
- §2.2 — revise — ambiguity — object-response `meta` carries only the two request fields, no pagination keys — `envelope.py:43-44`
- §2.3 — revise — mismatch — out-of-range/non-integer `limit`/`offset` are clamped or fall back to defaults, never refused; plus filter semantics (exact string equality -> empty page, boolean filter vocabulary, unknown query params ignored) — `envelope.py:65-81`, `common.py:58-77`
- §2.3 — revise — ambiguity — `created_at` ties broken by server creation order; ordering/filtering applied before the page cut; `limit`/`offset` echo effective values; `has_more` defined as `offset + len(page) < total_count` — `store.py:217-218`, `envelope.py:47-53,84-89`
- §2.4 — insert — ambiguity — version/`updated_at` move at most once per resource per request (target-of-disposition included), and a resource created by the request stays at `version` 1 with `updated_at == created_at` — `store.py:152-174,194-204`
- §2.4 — insert — ambiguity — declared-field-only payloads with unset fields as null; request-scoped rollback: a failing request writes nothing and moves no audit field, whatever check raised it — `serialize.py:97-98`, `store.py:177-191`, `app.py:33-56`
- §2.5 — revise — ambiguity — `to_iso8601` accepts `Z`, numeric offset (normalized to UTC) or no designator (read as UTC); absent/unparseable -> `ERR_INVALID_REQUEST`; response is that single `current_utc` key — `store.py:99-115`, `routes/clock.py:17-22`
- §2.6 check 5 — insert — ambiguity — absent/non-string/unrecognized `action` is not a role failure; it falls through to check 8 -> 400 — `auth.py:41-57`
- §2.6 check 8 — insert — ambiguity — a bodyless request is read as `{}`; a non-object/malformed body is itself `ERR_INVALID_REQUEST` — `validate.py:14-23`
- §2.6 check 8 — insert — ambiguity — JSON `null` is treated as absent (default or "required" error); blank/whitespace strings and wrong scalar types fail — `validate.py:26-27,34-49,63-70`
- §2.6 check 9 — insert — ambiguity — unresolved body FKs report the same per-collection not-found identifier as check 7 — `common.py:8-42`, cross-checked at `routes/assignments.py:129-132`, `routes/signings.py:74-76`
- §2.8 — insert — ambiguity — fixed-scale numbers are emitted as bare JSON numbers with exactly their declared fractional digits (never ints, never strings), input numbers with excess digits are quantized rather than refused, string/boolean numerics -> 400 — `envelope.py:15-29`, `validate.py:78-100`
- §2.9 — revise — ambiguity — the minor-deficiency tally is internal; `open_major_deficiency_count` is the only exposed tally — `serialize.py:5-10`
- §4 preamble — insert — ambiguity — trailing slash is optional on every path — `app.py:22`
- §5 preamble — insert — mismatch — transport-level failures documented (`ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500), rendered through the same error envelope — `app.py:38-56`
- §5 table — insert — mismatch — three rows added for those identifiers — `errors.py:71-73`

Cross-checks: the §5 error table and `errors.ERROR_STATUS` agree exactly on all 57 pre-existing identifiers (no status mismatches); the three extras were the only gap. §2.7's claim that each guarded create bumps its parent's `version` is genuinely forced by `store.touch` at `routes/staff.py:142`, `routes/assignments.py:164`, `routes/signings.py:98`, so the "at most one bump per request" wording does not contradict it.

### Pass 2 — club-side modules

469 lines before -> **469** after (all edits in-paragraph); chars 112,169 -> **115,659** (+3,490). **12 ambiguity-pins, 2 mismatch-revisions** (14 edits).

- §2.9 — revise — mismatch — "its single agreement in status SUBMITTED/ACTIVE/SUSPENDED" was wrong on two counts: `posture` is maintained on *every* agreement row (DRAFT/REJECTED/TERMINATED read `FROZEN` from their own status), and where a gate must pick one licence it takes the **most recently created** non-terminal row (a suspended licence can legitimately coexist with a submitted/activated successor); also scoped that selection to the staff-allocation proposal, the only path that tests posture without first requiring an `ACTIVE` licence — `derive.py:35-40,214-229`, `routes/staff.py:117`
- §2.9 — revise — ambiguity — added the second tie-break in the per-category latest-inspection roll-up: after `review_date` and `created_at`, ties go to the row the server created later — `derive.py:167-171`
- §3.1 — revise — ambiguity — `market_city` held to the same shape as `name`: 1-120 chars, not blank — `routes/affiliates.py:24`
- §3.1 — insert — ambiguity — a newly filed inspection carries `remediation_note`, `remediation_submitted_at`, `waiver_granted_by_user_id` null and `reopen_count` 0 (deliberately did *not* claim `is_overdue` false — a back-dated inspection returns `true` from the creating request) — `routes/reviews.py:44-57`
- §3.1 — revise — ambiguity — `remediation_note` optional, stored null when omitted, accepted when blank — `routes/reviews.py:85-86`
- §3.1 — revise — mismatch — PRD claimed waiving "a clean `NONE` finding" yields `ERR_WAIVER_NOT_PERMITTED`; impl runs the status check first, so a `NONE` row sitting in `CLOSED` gets `ERR_INVALID_REVIEW_STATE`, and the severity refusal is reachable only after a reopening — `routes/reviews.py:89-106`
- §3.1 — revise — ambiguity — an optional free-text `note` may accompany any inspection disposition, unstored — `routes/reviews.py:87`
- §3.2 — revise — ambiguity — the four declared expense figures must be zero-or-positive whole-cent integers — `routes/agreements.py:62-69`
- §3.2 — revise — ambiguity — a disposition `note` is accepted even when blank and is not persisted — `routes/agreements.py:129`
- §3.3 — revise — ambiguity — audited figures must be zero-or-positive; omitted or `null` ones stay null with the declared figure standing in — `routes/agreements.py:126-128,174-176`
- §3.4 — revise — ambiguity — `full_name` 1-120 chars not blank; `curriculum_version_certified` is any non-blank string, not checked against `2026.1` at registration — `routes/staff.py:41-44`
- §3.4 — insert — ambiguity — allocation proposal: posture comes from the club's non-terminal licence, so a DRAFT-only or licence-less club has no posture and the proposal proceeds (proposal never requires an `ACTIVE` licence, nor consults certification expiry); body FKs resolve `staff_member_id` before `affiliate_id` — `routes/staff.py:111-128`
- §3.4 — revise — ambiguity — `total_committed_fte_pct` is clock-dependent and re-derived for every member whenever the logical clock is set — `derive.py:290-302`, `routes/clock.py:21`
- §3.4 — revise — ambiguity — an allocation disposition `note` is not stored — `routes/staff.py:156`

Pass 2 raised one cross-slice defect it correctly declined to fix in another pass's territory: Pass 1's universal "a string field is never satisfied by whitespace alone" in §2.6 check 8 is contradicted by every optional narrative `note` field (all `allow_blank=True`). The orchestrator carried this over to Pass 3 as an explicit authorized carve-out.

### Pass 3 — player-side modules (+ authorized §2.6 carve-over)

469 lines before -> 469 after; chars 115,659 -> **124,295** (+8,636). **19 ambiguity-pins, 9 mismatch-revisions** (28 edits).

Carve-over (confirmed made): §2.6 check 8's universal blank-rejection claim replaced with a scoped one — identifying/constrained strings (`name`, `market_city`, `full_name`, `curriculum_version`, `curriculum_version_certified`, body foreign keys, `curriculum_modules` entries) are never satisfied by whitespace alone, whereas the optional narrative fields (`note`, `remediation_note`, `revision_note`, `restriction_note`, `league_note`) tolerate a blank value and store it as supplied. Verified against `validate.py:34-49` plus every `str_field`/`id_field`/`enum_list_field` caller.

- §2.6 — revise — mismatch — blank-rejection rescoped from universal to required/identifying strings vs. optional narrative notes — `validate.py:43` + all callers
- §3.5 — insert — ambiguity — player `full_name` bounded 1-120 and non-blank — `routes/players.py:36`
- §3.5 — revise — mismatch — clearance revocation drives `roster_status` to `RESTRICTED` from any of the three values, not only from `ACTIVE`; `current_affiliate_id` clears only with the suspended level/complex row — `routes/players.py:180`
- §3.5 — revise — ambiguity — `expires_on` is mandatory on `ISSUE` and its refusal (check 8) precedes `ERR_INVALID_CLEARANCE_STATE` — `routes/players.py:128-132`
- §3.5 — insert — ambiguity — "no active assignment" means no assignment of any type in `ACTIVE`, rehab included — `routes/players.py:155`
- §3.5 — insert — ambiguity — `restriction_note` optional, null when omitted, blank tolerated — `routes/players.py:125`
- §3.5 — revise — mismatch — revocation forces `RESTRICTED` unconditionally; `current_affiliate_id` survives when the revoked type suspended nothing — `routes/players.py:166-180`
- §3.6 — insert — ambiguity — body FKs resolved `player_id` -> `affiliate_id` -> `superseded_assignment_id`; the superseded row's type/owner/status are not policed — `routes/assignments.py:112-132`
- §3.6 — revise — mismatch — reserve-list test applies only to `LEVEL`/`COMPLEX`, only to a domestic-reserve player, and is skipped when `current_affiliate_id` is already this club — `routes/assignments.py:245-249`
- §3.6 — revise — ambiguity — the displaced prior row completes down the full `COMPLETE` path (plans lapse; a `REHAB` prior emits `REHAB_COMPLETE`) — `routes/assignments.py:263-267`, `flows.py:118`
- §3.6 — insert — ambiguity — the `REHAB_COMPLETE` gate on completion never tests lapse — `routes/assignments.py:274`
- §3.6 — revise — mismatch — suspension moves the player's standing only when the row was the last `ACTIVE` level/complex one; a `REHAB` suspension leaves both standings alone — `flows.py:81-101`
- §3.6 — revise — mismatch — resumption tests roster capacity only for `LEVEL`/`COMPLEX`; `roster_status` becomes `ACTIVE` whatever the type while `current_affiliate_id` stays derived — `routes/assignments.py:285-290`
- §3.6 — insert — ambiguity — disposition `note` blank-tolerated and not persisted — `routes/assignments.py:217`
- §3.7 — insert — ambiguity — module entries are non-blank strings from no fixed vocabulary; plans attach only to `PENDING_CLEARANCE`/`ACTIVE`/`SUSPENDED`, status before curriculum — `routes/plans.py:37-49`
- §3.7 — insert — mismatch — plan-activation preconditions run in §2.6 order, so duplicate-plan precedes curriculum — `routes/plans.py:105-109`
- §3.7 — revise — ambiguity — an omitted `completed_module_count` is also `ERR_INVALID_REQUEST`, but all four progress refusals are judged after the plan-status check; only field shape precedes it — `routes/plans.py:86,111-117`
- §3.7 — insert — ambiguity — `revision_note` optional/null/blank-tolerated — `routes/plans.py:88`
- §3.7 — insert — ambiguity — outings attach only to live assignments; `log_date` is unconstrained relative to the clock — `routes/plans.py:151,162`
- §3.7 — insert — ambiguity — with `ACTIVE` plans on two assignments, the most recently created supplies both the allowance and the readiness inputs — `derive.py:109-112`
- §3.7 — revise — ambiguity — the ceiling comparison uses the rounded, 25.00-capped `workload_index`, is strict, and rehab outings can never breach; governing clearance = latest non-expired `ISSUED` of the required type, falling back to the latest lapsed one — `routes/plans.py:180-183`, `derive.py:141-157`
- §3.7 — revise — mismatch — the recomputation list omitted `MARK_ACHIEVED`, which drops the plan allowance out of the projected index — `routes/plans.py:139`, `derive.py:255`
- §3.7 — insert — ambiguity — the promotion rank baseline is a four-step search (latest `ACTIVE` level/complex -> superseded row -> latest level/complex in any status -> rank below everything), with the activating row excluded — `routes/assignments.py:56-72,234-236`
- §3.8 — revise — mismatch — a new report's `is_late`/`late_fee_cents` are immediately re-priced in the creating request, so `REVOCATION`/`RECALL` reports can be born late — `flows.py:21-38`, `derive.py:326-340`
- §3.8 — insert — ambiguity — `league_note` optional/blank-tolerated and survives a refiling — `routes/reports.py:36,63-67`
- §3.9 — insert — ambiguity — signing FKs resolved `pool_id` -> `player_id` -> `academy_affiliate_id` — `routes/signings.py:74-76`
- §3.9 — insert — mismatch — approval preconditions run in §2.6 order: licence gates before pool status and beds — `routes/signings.py:141-155`
- §3.9 — insert — ambiguity — a voided signing keeps its own `pool_charge_cents`, `overage_tax_cents` and `tier3_breach`; only the pool's aggregates change — `routes/signings.py:177-186`, `derive.py:315-323`

### Step 9 totals and orchestrator verification

Across the three passes: **59 edits — 46 ambiguity-pins, 13 mismatch-revisions.** `PRD_FINALIZED.md` 460 lines / 105,493 chars -> `PRD_COMPLETED.md` 469 lines / 124,295 chars (+9 lines, +18,802 chars, +17.8%).

Verification: `cmp` confirms `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` (the known failure mode where the scan never actually ran); all five top-level sections are present; the tail ends at `| ERR_INTERNAL | 500 |`, the final row of the now-60-row §5 error table, not mid-sentence; `grep` for the difficulty directive and for "SCAFFOLD" returns 0 hits. Step 9 touched only `PRD_COMPLETED.md`, so Step 7's green state stands: all 8 `results.{1..8}.json` remain on disk at 102/102 passing.

**PIPELINE COMPLETE** — Step 9 has written `workspace/PRD_COMPLETED.md`.
