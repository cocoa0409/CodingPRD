# Worklog — task_2480_disaster_public_assistance_grant_administration

## Step 1: Create task directory — 2026-09-02T23:19:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2480_disaster_public_assistance_grant_administration` and its `workspace/` subdirectory. Index 2480 was pre-assigned by the orchestrating caller; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate Scaffold — 2026-09-03T01:07:00.000Z

All three scaffold artifacts are complete and lint-clean.

**Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2480_disaster_public_assistance_grant_administration/`)**
- `SCAFFOLD.yaml` — §1.0–§1.7 plus preamble; contains neither `scaffold_difficulty_design` nor `scaffold_corner_design` (verified programmatically).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`.

**Lint verdict (verbatim)**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2480_disaster_public_assistance_grant_administration/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2480_disaster_public_assistance_grant_administration/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2480_disaster_public_assistance_grant_administration/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    62
  §1.1 entities declared:     13
  §1.8 instances scanned:     25
  §1.9 instances scanned:     71
  Calls scanned (§1.8+§1.9):  1117

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Scaffold size (§1.0–§1.7)**
- 13 entities (Disaster, Applicant, Facility, DamageSite, ForceAccountResource, Contract, InsurancePolicy, Project, CostLineItem, Drawdown, ProgressReport, Deobligation, Appeal); topology `flat`, state-machine shape `cyclic`, role model `segregation_of_duties`.
- 62 endpoints under prefix `/public-assistance`, 62 error codes (every one referenced by at least one design instance — checked), 37 priority-ordered validations, 13 calculations, 11 state machines, 6 roles, 2 `concurrency_rules`.
- Active complexity layers: `dual_variant_calculation`, `cascading_side_effects`, `rate_threshold_triggers`, `optimistic_concurrency`.

**§1.8 depth probe — 9 rules, 25 instances (all with `test_recipe`)**
`dual_variant_calc` (2), `combinatorial_formula` (3), `non_linear_state_machine` (3), `transitive_cascade` (2), `priority_pair_validation_conflict` (3), `boundary_precision_check` (3), `cross_entity_state_dependency` (4), `resource_temporal_overlap` (3), `compensating_invariant` (2).

**§1.9 breadth probe — all 9 sections, 99 instances (71 real recipes + 28 `excluded_because` stubs)**
entities 12 (12/0), state_machines 18 (14/4), calculations 20 (13/7), validations 28 (15/13), endpoints 5 (5/0), errors 4 (2/2), rbac 6 (6/0), cross_cutting_complexity_layers 5 (3/2), consistency_model 1 (1/0). Instance names are unique across the union of both design files, and all 28 stub `difficulty_instance` references resolve to a real `rule_id / instance_name` pair.

**Two pre-existing defects found and fixed while getting to a clean lint**
1. `SCAFFOLD.yaml` was not YAML-parseable: 30 flow sequences carried optional-input markers as bare scalars (e.g. `input: [..., federal_cost_share_pct?]`); PyYAML rejects `?` in a plain scalar inside `[...]`. Each such element is now quoted (`"federal_cost_share_pct?"`).
2. `SCAFFOLD_DIFFICULTY_DESIGN.yaml:691` had `captures: { report_id: $.data[0].id }` — the `[` opened a flow sequence inside a flow mapping and broke the parse; now quoted (the lint accepts the `$.data[N].field` form).

## Step 3: Copy Shared Files — 2026-09-03T01:18:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T01:36:00.000Z

PRD complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2480_disaster_public_assistance_grant_administration/workspace/PRD.md`
**Final line count:** 495. **Last section heading:** `## 5. Error Code Catalogue`, ending on the completed 62-row error table (`| \`ERR_NO_DOCUMENTED_COSTS\` | 409 |`) — no chunk marker left, no mid-sentence truncation.

**Structure:** §1 Introduction; §2 Global Specifications (10 subsections: RBAC, response structure verbatim, pagination, common properties, logical clock, money/rounding, 37-rung validation ladder, optimistic concurrency, cascade consistency + conserved ledger quantities, segregation of duties); §3 Business Logic (9 chronological workflow subsections, declaration → applicants → facilities/damage → project formulation/RFI → cost record → cost-line review → insurance DOB waterfall → cost review/mitigation cap/obligation → drawdowns/reporting → closeout/deobligation/appeals); §4 Endpoint Definitions (4-column table, 62 rows); §5 Error Code Catalogue (2-column table, 62 rows).

**Hard Contract 1 — Field-Name Coverage: PASS.** Two independent passes. Pass A parsed SCAFFOLD.yaml structurally: 169 `entities[].fields[].name` values and 73 `request_body`/`input`/`query_params`/`path_params` identifiers — 0 missing from the PRD's backticked-token set (546 distinct backtick spans, code fences excluded from pairing). Pass B re-derived names by regex over the raw YAML text; the only 13 unmatched snake_case names were internal `calculations[].name` values (`project_review_basis`, `mitigation_cap_allocation`, `federal_share_obligation`, `applicant_grant_ledger`, `closeout_reconciliation`, etc.), which are not Contract 1 targets — their behaviour is described in prose. Also checked: 112 enum literals across all field `constraints` — 0 missing; all endpoint-level enum literals — 0 missing.

**Hard Contract 2 — Rule Coverage: PASS.** All 62 catalogued error ids appear in backticks in the body (independent of the §5 table); every alternation in `validations[].error_id` resolved to ids all present. All 11 state machines and all 40 transitions covered, including the qualified-state families (`ELIGIBILITY:*`, `MONITORING:*`, `DRAWDOWN:*`) — one edit was made during verification to name `ELIGIBILITY:PENDING → ELIGIBILITY:ELIGIBLE` / `→ ELIGIBILITY:INELIGIBLE` explicitly in §3.1. All 13 calculations documented with every output field named, including both variant pairs (`PROVISIONAL`/`FINAL` cost, `SCREENING`/`MONITORING` risk) and the pinned per-component rounding at obligation and closeout. Both `concurrency_rules` (`expected_applicant_version`/`ERR_STALE_APPLICANT_VERSION`, `expected_project_version`/`ERR_STALE_PROJECT_VERSION`) present with their non-optional status and 412 mapping. Both segregation-of-duties separations, both depth-4 cascades, the sticky `audit_requirement`/`monitoring_status` high-water marks, the reversible `drawdown_status`, and sibling-branch symmetry (VALIDATE/DENY, PAY/REJECT, GRANT/PARTIALLY_GRANT/DENY/REMAND, SMALL/LARGE closeout) all documented.

**Hard Contract 3 — §3 Path Purity: PASS.** 1102 backticked spans inside §3 scanned; 0 begin with `/`, 0 are a bare HTTP method, 0 combine method + path, and 0 contain a path-like segment. Every §3 operation is introduced by state transition, role + action verb, or capability description.

Additional checks: §2.2 is byte-identical to `section-2.2-response-structure.md`; exactly 2 code fences in the document (both inside §2.2); §4 table has exactly 4 columns and every one of the scaffold's 62 method+path pairs, §5 exactly 2; no unbalanced backtick lines; no fuzzy quantity words. The two withheld design files were never opened.

**Orchestrator truncation check (per caller's guard):** independently verified — `wc -l` = 494, tail shows the error table completing at `| ` + "ERR_NO_DOCUMENTED_COSTS" + ` | 409 |` followed only by blank lines; section headings present at lines 3/11/195/357/426. Ends at a real section boundary. No regeneration needed.

## Step 5: Generate Unit Tests — 2026-09-03T02:38:00.000Z

Task complete. Both stages are on disk, all 11 Stage 2 agents have reported, and the full verification battery is clean.

## Files written

**Stage 1 — `/home/ubuntu/github/CodingPRD/tasks/task_2480_disaster_public_assistance_grant_administration/test_helpers/`** (9 files)
`__init__.py` (barrel), `types.py` (UserRole + ~30 vocabulary enums + 13 TypedDicts), `api_client.py` (`ApiClient(GenericApiClient)`, 65 endpoint methods, `PREFIX = "/public-assistance"`), `api_errors.py` (62-member `ApiErrorId`, `HTTP_STATUS_CODES`, `set_error_http_status_map` registered at import), `assertions.py`, `factories.py` (14 payload builders), `constants.py`, `test_users.py` (incl. the mandatory `make_applicant_agent_headers(applicant_id)`), `fixtures.py` (~50 step helpers + 15 `setup_*` scenario composites).

**Stage 2 — `.../test_suite/`** (12 files)
`conftest.py` plus `test_01_` … `test_11_`, split by domain language: cost computation & federal share (11), lifecycle branches & cascades (16), evaluation order & boundaries (13), cross-entity gates & ledger conservation (12), temporal overlap & capacity (9), resource records & reads (12), state transitions (17), computation rules (13), validation rules (21), access control & versioning (9), endpoint surface & consistency (13).

## Test counts

- **146 test functions → 156 collected cases** (parametrized expansion), collected in 0.81s.
- **Queue A (Difficulty, §1.8): 61 tests** over all 25 instances — every instance has >=2.
- **Queue B (Corner, §1.9): 85 tests** over all 71 non-stub instances — every instance has >=1.
- The 28 `excluded_because:` corner stubs were verified to cross-reference real §1.8 instance names and were correctly left untranslated.

## Instances skipped

**Zero.** All 25 difficulty and all 71 non-stub corner instances passed the PRD-first two-condition filter. Gaps were absorbed at the *individual assertion* level instead, uniformly across agents:

- **Pinned literal timestamps** (`"2026-07-01T00:00:00Z"`, `"2026-08-30T00:00:00Z"`, …) — PRD §2.4 mandates three fractional digits, so exact-string equality is not uniquely derivable. Replaced with parsed-instant comparison or prefix match; the pinned values are preserved.
- **Query-parameter names for list filters** (`?project_id=`, `?deobligation_id=`, `?prior_appeal_id=`, `?level=`) — §2.3 names only `limit`/`offset` and illustrates conjunction with `applicant_id`+`status`; the rest are never spelled out. Replaced with unfiltered lists plus `meta["total_count"]` / client-side narrowing (sound because the harness wipes the DB before every individual test).
- A handful of recipe assertions on fields the PRD never states are persisted (`Project.submitted_at`, `audit_finding` on the project, `disbursed_by_user_id` null on the REJECT branch) were dropped; instance coverage retained.

## Adjudications worth flagging

- **`validation-priority` silence pattern does not bite here.** PRD §2.7 verbatim pins a fixed 37-rung order ("the **first** failing rung decides the response", "A later rung never masks an earlier one") with each rung's error id, so priority-conflict instances got hard `validate_error(...)` assertions plus companion tests isolating the losing guard.
- **The `error-precedence` relaxation was used exactly once**, in `cost_line_item_referencing_another_applicants_resource_rejected`, where §2.7 rung 3's ownership scope plausibly pre-empts rung 21's containment check.
- **Appeal-decision wire literals** (`GRANT`/`PARTIALLY_GRANT`/`DENY`/`REMAND`) are not spelled out in the PRD; derived from its imperative-verb convention for every other decision field plus the §4 endpoint row.

## Stage 1 defect found and fixed

The endpoint-surface agent flagged that `test_helpers/assertions.py`'s `assert_error_envelope` / `assert_success_envelope` asserted an `ok` / `error` / `data: null` body shape, contradicting the PRD §2.2 envelope (`meta` / `response_type` / `data`, with `error_id` and `message` inside `data` on failure). I rewrote both to be PRD-faithful — they now check the `req_`-prefixed `api_request_id`, the ISO 8601 `api_request_timestamp`, `response_type`, the error-meta key restriction, and the `data` payload. No test used them, so nothing else changed; helpers still import cleanly and collection is unaffected.

## Verification

Audit clean (`Design:` uniqueness/resolution, coverage floors, verbatim PRD citation matching under whitespace normalization); 156 tests collect; no forbidden vocabulary (`scaffold`, `§1.x`, design-index names) anywhere in generated code; no `validate_paginated` extra-arg or `run_race([...])` misuse; no `mark.skip`/`mark.xfail`/`pytest.skip(`; no duplicate test names; no test consumes the shared `applicant_agent_headers` fixture (all ownership-gated calls go through the per-applicant builder); `__pycache__` removed. Nothing under `workspace/implementation/` was read or written by me or by any of the 11 subagents.

## Step 6: Generate Implementation — 2026-09-03T02:38:00.000Z

Implementation is complete and verified.

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_2480_disaster_public_assistance_grant_administration/workspace/implementation/`:

- `start.sh` (now `chmod +x` — it was non-executable, which would have broken every harness reboot), `requirements.txt` (`flask>=2.0`)
- `app.py` — factory, 12 blueprints, global `RLock` per request, `ApiError`/404/405/500 handlers, `/health`, `exec` on `PORT` (default 10000), bind `0.0.0.0`
- Core: `db.py` (in-memory `Store` over 13 collections, logical clock, dirty-row version tracking), `errors.py`, `response.py`, `middleware.py`, `validate.py`
- `services/`: `constants.py`, `calc.py` (all 13 SCAFFOLD §1.3 calculations), `ledger.py` (cascades, rollups, waterfall, report scheduling)
- `routes/`: `common.py`, `disasters.py`, `applicants.py`, `facilities.py`, `damage_sites.py`, `resources.py` (force-account + contracts), `insurance.py`, `projects.py`, `cost_line_items.py`, `drawdowns.py`, `progress_reports.py`, `deobligations.py`, `appeals.py`

**62 domain endpoints** registered under `/public-assistance` — an exact 1:1 match with the 62 method+path pairs in SCAFFOLD §1.5 (plus `/health`). Storage is Python dicts only; no seeding, no disk, no SQLite — every boot is empty. Scratch smoke files were removed; `__pycache__` cleaned.

## Verification
- Three scratch end-to-end walks (~130 assertions) passed with zero failures before deletion: full lifecycle, flood-insurance bar, single-audit escalation with auto-created DUE report, delinquency sweep/cure, disaster rollups, close-obligations, pagination/auth/404, and a targeted contract-ceiling ordering test.
- Booted a real server through `start.sh` on a spare port: `/health`, a list read, and a clock set all returned 200 with the correct envelope and 3-fractional-digit instants.

## Coverage
State machines: Disaster (DECLARED→OBLIGATIONS_CLOSED), Applicant eligibility + `monitoring_status`/`audit_requirement` high-water marks vs oscillating `drawdown_status`, Facility screening, DamageAssessmentSite, Project (DRAFT→UNDER_REVIEW→RFI_ISSUED→VALIDATED→OBLIGATED→CLOSEOUT_REQUESTED→CLOSED / DENIED), CostLineItem review, Contract procurement, Drawdown (REQUESTED→PAID→REFUNDED / REJECTED), ProgressReport (DUE→DELINQUENT→SUBMITTED|LATE), Deobligation (PROPOSED→FINAL→REVERSED, with remand back to PROPOSED), Appeal (SUBMITTED→GRANTED|PARTIALLY_GRANTED|DENIED|REMANDED).

Calculations: all 13 audited line-by-line against SCAFFOLD §1.3 — validated-loss indicator, facility screening cascade, procurement cascade, cost-line eligible cost (labor/equipment/contract), project review basis, mitigation cap, federal share obligation, insurance DoB waterfall, project eligible cost (PROVISIONAL + FINAL), risk score (SCREENING + MONITORING), grant ledger, report schedule, closeout reconciliation. Pinned rounding respected: 3 roundings for labor, 2 independent per-component roundings for federal share and closeout; floors for caps/ratios.

## Ambiguities resolved
1. **Contract ceiling sibling order (fixed this session).** I had been tie-breaking equal `created_at` with an insertion sequence. PRD §3.5 and SCAFFOLD line 1015/1027 both pin *strictly earlier* `created_at` with the identifier never consulted, so I switched to a literal `other["created_at"] < line["created_at"]`. Consequence, now covered by test: two contract lines created in the same frozen logical instant do **not** consume each other's headroom.
2. **Drawdown-create validation order.** PRD §3.7's prose lists applicant eligibility before project state, contradicting the ladder. Followed the ladder (§2.7 rung 8 project-OBLIGATED before rung 19 applicant-ELIGIBLE), since §2.7 and SCAFFOLD `validations[].priority` agree rung-for-rung.
3. **Three uncatalogued 409s.** SCAFFOLD §1.6 has no error id for the applicant-, facility- and deobligation-state preconditions the PRD still pins, so I added `ERR_APPLICANT_INVALID_STATE`, `ERR_FACILITY_INVALID_STATE`, `ERR_DEOBLIGATION_INVALID_STATE` (all 409), documented at the top of `app.py`.
4. **REMAND on a second-level appeal** has no catalogued error; refused with `ERR_INVALID_REQUEST`.
5. **Partial reversal** keeps the determination at `FINAL` (only `reversed_cents >= amount_cents` flips it to `REVERSED`), which is what makes the two conserved-quantity invariants hold; `deobligated_cents` and `pending_deobligation_cents` are always rederived from the determination set rather than incremented.
6. **Version semantics.** Rows created within a request stay at version 1; cascaded rows bump only when a stored value actually moves, except where a side-effect list states an unconditional increment (e.g. drawdown create always bumps `Applicant.version`), where I force it.

One environment note: a `python3 app.py` process for **task_2484** is running on the host — unrelated to this task, left untouched.

### Orchestrator note on Step 5/6 launch (isolation)

The skill requires Steps 5 and 6 to be launched in a *single* assistant message so that the impl generator is physically unable to see `test_suite/` (it does not exist yet at its spawn time). In this run the two Agent calls landed in two consecutive messages, so physical isolation was not guaranteed by construction. Mitigation applied at spawn time: Step 6's prompt carried an ABSOLUTE HARD CONSTRAINT forbidding any read/list/glob/grep/stat of `test_suite/`, `test_helpers/`, both design YAMLs, and sibling task directories. The Step 6 agent's returned summary independently confirms it built strictly from INSTRUCTION.md + SCAFFOLD.yaml + PRD.md, and the Step 5 agent confirms nothing under `workspace/implementation/` was read or written by it or any of its 11 subagents. Test-blindness therefore holds by declaration rather than by filesystem accident; recorded here rather than silently.

## Step 7: Run Tests and Iterate — 2026-09-03T02:32:00.000Z

The task is already fully green — no fixes were needed.

## Summary

**Iterations run: 1** (a single 8-round parallel stability sweep, launched under `setsid nohup` and joined with `wait`).

**Sweep result: all 8 rounds green.** Every `results.$i.json` (i = 1..8) parses and reports `passed=156 total=156 failed=0 errors=0 skipped=0`. The union of non-passing tests across all 8 rounds is empty, so there is no flakiness signal to chase. Each round took ~299s wall time; all 8 ran concurrently.

- **Tests deleted:** none. No test failed either sub-check of STEP 1, because no test failed at all — the diagnostic protocol never engaged.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `implementation/`:** none.

Notes worth relaying:

- One process note on my own method: my first pass at reading the results keyed on a nonexistent `outcome` field instead of the runner's actual `status` field, which made all 156 tests look like they failed in all 8 rounds. The results schema is `{total, passed, failed, errors, skipped, duration_seconds, tests[{name, file, status, duration_seconds, error_message}]}`. Re-parsed against `status`, the union of failures is genuinely empty. Flagging this because the transient "156 failures × 8 rounds" reading was an artifact of my parser, not of the implementation.
- Hygiene checks required by the benchmark contract both pass: there are zero `pytest.mark.skip` / `xfail` markers anywhere in `test_suite/` or `test_helpers/`, and the implementation carries no disk persistence or startup seeding (the sole grep hit is a docstring in `.../workspace/implementation/db.py` line 4 asserting in-memory-only storage, consistent with `start.sh` re-invocation wiping all state under per-test-server isolation).
- The 8 `results.*.json` files remain in `.../workspace/implementation/` and the combined runner output in `.../workspace/sweep.log`, in case you want the raw evidence. The whole task directory is still untracked in git; no commits were made and no files changed.

### Orchestrator independent re-verification of the sweep artifacts

Because a Step 7 subagent's clean-sweep claim is not self-certifying, the orchestrator re-parsed the artifacts directly rather than taking the summary at face value. All 8 `results.{1..8}.json` exist on disk (each ~48.8 KB, mtime 02:26), all 8 parse as complete JSON, and each independently reports `total=156 passed=156 failed=0 errors=0 skipped=0` with a per-round `duration_seconds` of 299 and an empty set of tests whose `status != "passed"`. The green result is confirmed on the artifacts, not on the subagent's word.

## Step 8: Finalize PRD — 2026-09-03T02:33:00.000Z

**SKIPPED — skip condition met.** Step 7 exited on its first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. Per the skill's Step 8 skip condition, `PRD.md` already determined every behavior the implementation exhibits at every site the test suite exercised, so there is no `<step_7_diff>` to target and no finalizer subagent was spawned. `workspace/PRD_FINALIZED.md` is therefore intentionally absent, and Step 9 will start from `workspace/PRD.md`.

Note that this does NOT mean the PRD is free of silences: Step 6 self-reported six interpretation decisions it made at generation time (contract-ceiling sibling ordering on equal `created_at`, drawdown-create ladder-vs-prose ordering, three uncatalogued 409 error ids, REMAND-on-second-level-appeal refusal, partial-reversal keeping `FINAL`, and version-bump semantics). Those resolved PRD ambiguities without ever producing a Step 7 failure signal, which is precisely the class of gap Step 9's full implementation scan exists to close.

## Step 9: Complete PRD — 2026-09-03T02:58:00.000Z

Done. Verified complete and untruncated.

## Verification
- `workspace/PRD.md`: **494 lines / 106,575 chars**
- `workspace/PRD_COMPLETED.md`: **497 lines / 126,147 chars** (**+19,572 chars**, +3 lines = the 3 new §5 rows)
- File ends at a real boundary: §5 error catalogue, now **65 rows** (was 62), last row `| ERR_NO_DOCUMENTED_COSTS | 409 |`, followed by the same trailing blank lines as the source. No mid-sentence truncation.
- Changes touch 47 existing lines + 3 inserted table rows; **no new sections, no new paragraphs** — every prose change is an in-paragraph insert or revision.

**48 changes: 32 ambiguity-pins, 16 mismatch-revisions.** All six known-silence leads confirmed in code and pinned (a: §3.5/282, b: §3.8/318, c: §2.7/133 + §5, d: §3.9/346+351, e: §2.9/182 + §3.9/353+355, f: §2.4/98 + eight per-operation version clauses).

### Changes
- §2.1 — revise — ambiguity — a header that is present but empty/whitespace counts as absent (401); surrounding whitespace otherwise trimmed from both header values — `middleware.py:41-43`
- §2.1 — insert — ambiguity — single-resource GETs of applicant-scoped rows do enforce ownership; **no list endpoint filters or checks ownership at all** — `routes/common.py:39-51`, `routes/facilities.py:66`
- §2.3 — revise — ambiguity — list order breaks equal `created_at` by creation sequence, never by id; unrecognized query params ignored, not rejected; each collection's classifying enum is also a filter — `db.py:170`, `routes/common.py:43-48`
- §2.4 — revise — ambiguity — `created_at`/`updated_at` both read the logical clock; `updated_at` equals `created_at` on a fresh row — `db.py:123-133`
- §2.4 — insert — ambiguity — the three version rules: created rows stay at 1, named target bumps unconditionally, cascade-reached rows bump only when a stored value moves (unless §3 says otherwise) — `db.py:120,138,148`
- §2.4 — revise — mismatch — `settled_at` removed from the clock-written list; it is client-supplied and stored as supplied — `routes/insurance.py:88,105`
- §2.5 — revise — mismatch — "nothing reads the host wall clock" excepted for the envelope's `api_request_timestamp`; clock may be set backwards or equal — `response.py:15,24`, `routes/disasters.py:27`
- §2.5 — insert — ambiguity — client instants stored verbatim; ISO 8601 accepted generously (optional seconds, 1–9 fractional digits, `T`/space, `Z`/`±HH:MM`/`±HHMM`/no zone = UTC); comparisons on the UTC equivalent — `db.py:62-86`
- §2.7 — insert — ambiguity — rung 3 examines exactly one subject per endpoint (path row, or the named body reference); other applicant-scoped FKs fall through to rung 21; unresolvable indirect refs skip the rung; direct `applicant_id` compared raw — `middleware.py:51`, `routes/cost_line_items.py:40-44`
- §2.7 — insert — ambiguity — rung 5 also carries: negative `expected_*_version` is a shape failure (never 412), and `REMAND` on a non-FIRST appeal — `routes/drawdowns.py:26`, `routes/appeals.py:134`
- §2.7 — revise — ambiguity — added the three uncatalogued 409 ids to rung 8 and pinned target-row-first ordering — `errors.py:77-79`, `routes/deobligations.py:96-103`
- §2.9 — revise — mismatch — chain version bumps are not universal; they follow the three rules of §2.4 — `db.py:138-152`
- §2.9 — insert — ambiguity — project `deobligated_cents`/`pending_deobligation_cents` are rederived from the determination set, never incremented; `REVERSED` contributes to neither — `services/ledger.py:102-110`
- §2.9 — insert — ambiguity — `audit_requirement` is applied by every recomputation, but the `monitoring_status` escalation + spawned report fire only inside obligation — `services/ledger.py:111-144`, `routes/projects.py:269-313`
- §3.1 — revise — ambiguity — `federal_cost_share_pct` membership tested on the value reduced to two decimals; stored exactly as supplied — `routes/disasters.py:64-121`
- §3.1 — insert — ambiguity — re-determining a non-`PENDING` applicant → `ERR_APPLICANT_INVALID_STATE` (409), before the PNP/SBA prerequisite — `routes/applicants.py:87-124`
- §3.2 — revise — ambiguity — screening a non-`PENDING` facility → `ERR_FACILITY_INVALID_STATE` (409) — `routes/facilities.py:115-121`
- §3.2 — revise — ambiguity — all five amendment attributes optional; a no-op amendment still resets to `PENDING`, clears both fields and bumps `version` — `routes/facilities.py:81-110`
- §3.3 — revise — mismatch — submit guards reordered to ladder order: DRAFT → facility eligible → applicant eligible → declaration open (facility beats applicant) — `routes/projects.py:138-168`
- §3.3 — insert — ambiguity — RFI-response estimate must be an integer ≥ 0; the `ERR_MITIGATION_EXCEEDS_REPAIR` bar is not re-applied on revision — `routes/projects.py:190-219`
- §3.4 — insert — ambiguity — only `employee_type` is policed against `resource_kind`; all rate/code fields optional on either kind and stored unchecked — `routes/resources.py:20-64`, `services/calc.py:111-177`
- §3.4 — insert — ambiguity — hour fields are not policed against `cost_type`; `charged_hours_total` sums all three regardless — `routes/cost_line_items.py:53-58,231-239`
- §3.4 — revise — mismatch — cost-line creation guards reordered to ladder order: project locked → incident period → procurement → applicant eligible → cross-applicant; cross-applicant resource/contract always 409, never a scope violation — `routes/cost_line_items.py:86-111`
- §3.4 — insert — ambiguity — overlap/cap scans span all projects and all review statuses; an interval touches every UTC day from start-day through end-day inclusive and contributes its **whole** `equipment_hours` to each — `routes/cost_line_items.py:25-32,130-145`, `services/calc.py:316`
- §3.5 — revise — ambiguity — straight time is zeroed only for the literal `PERMANENT`+`EMERGENCY` pairing, so a null `work_type` (e.g. review while still DRAFT) leaves it billable — `services/calc.py:111-140`
- §3.5 — revise — ambiguity — the contract ceiling compares `created_at` alone with no secondary tie-break, so identical-instant siblings are invisible to each other — `routes/cost_line_items.py:209-220`
- §3.5 — revise — mismatch — the line bumps unconditionally, but the resource's and contract's `version` rise only when their recomputed totals move — `routes/cost_line_items.py:225-245`
- §3.6 — revise — mismatch — settlement guards reordered: policy effectiveness before the coverage bound; no already-settled guard, a repeat settlement overwrites and re-runs the waterfall on the new full amount — `routes/insurance.py:88-107`
- §3.6 — revise — ambiguity — waterfall visits candidates by category then creation order for identical `created_at` — `services/ledger.py:262-300`
- §3.6 — revise — mismatch — policy bumps unconditionally even when nothing was allocated; visited projects/applicant/declaration bump only when a stored value moved; created determinations are version 1 — `routes/insurance.py:105-112`, `services/ledger.py:262-300`
- §3.7 — revise — mismatch — obligation guards reordered: `VALIDATED` → insurance bar → declaration open — `routes/projects.py:269-283`
- §3.7 — insert — ambiguity — the four declaration roll-ups pinned over all applicants; `total_drawn_cents` sums applicants' **`cash_on_hand_cents`**, not their `total_drawn_cents` — `services/ledger.py:145-157`
- §3.8 — revise — mismatch — drawdown-create guards reordered (version → project `OBLIGATED` → applicant eligible → cross-applicant → suspended → available) and the create's only outside effect is the applicant's version bump: no ledger or declaration movement — `routes/drawdowns.py:15-67`
- §3.8 — revise — ambiguity — `refund_cents` need only be ≥ 0; a zero refund is legitimate and still drives the row to `REFUNDED` — `routes/drawdowns.py:138-147`
- §3.8 — insert — ambiguity — quarter uniqueness polices applicant filings only (the §3.7 escalation row can coexist); malformed `quarter_label` → `ERR_INVALID_REQUEST` — `routes/progress_reports.py:35-49`
- §3.8 — revise — mismatch — `narrative` and `pct_complete` are mandatory on submit; the same clock test applies from `DELINQUENT`, so a filing at/before `due_at` lands `SUBMITTED`; applicant/declaration move only when leaving `DELINQUENT` — `routes/progress_reports.py:79-110`
- §3.8 — revise — mismatch — sweep re-scores monitoring **after** the delinquency pass; applicant `version` always +1 (`monitoring_scored_at` always stamped), declaration only if a roll-up moved — `routes/applicants.py:126-143`
- §3.9 — revise — mismatch — `audit_finding` is required (empty string allowed) but never stored; certification bumps the project unconditionally, applicant/declaration only when a value moved — `routes/projects.py:339-362`
- §3.9 — revise — mismatch — for a manually recorded determination the declaration's version rises only if a roll-up moved — `routes/deobligations.py:49-66`
- §3.9 — revise — ambiguity — finalization tests the determination's own status first (`ERR_DEOBLIGATION_INVALID_STATE`, 409) before the project's — `routes/deobligations.py:96-103`
- §3.9 — insert — ambiguity — appeal-filing guards ordered second-appeal → duplicate → level-exhausted, with the `relief_requested_cents` bound tested last — `routes/appeals.py:65-83`
- §3.9 — insert — ambiguity — decide guards ordered: REMAND-level test first, then already-decided, then segregation of duties — `routes/appeals.py:134-146`
- §3.9 — revise — ambiguity — `PARTIALLY_GRANT` rejects an omitted `relief_granted_cents` too, and that check runs after all three guards — `routes/appeals.py:150-156`
- §3.9 — revise — ambiguity — REMAND on a second-level appeal is refused with `ERR_INVALID_REQUEST` (422) — `routes/appeals.py:134`, `errors.py`
- §3.9 — revise — mismatch — `reversed_cents` **accumulates** across successive grants, and the determination flips to `REVERSED` when the total reaches **or exceeds** `amount_cents` (partial stays `FINAL`) — `routes/appeals.py:173-178`
- §3.9 — revise — mismatch — a remand leaves `reversed_cents` exactly as it stands, so a partially reversed determination returns to `PROPOSED` still carrying it — `routes/appeals.py:180-185`
- §4 — insert — ambiguity — framework answers `ERR_NOT_FOUND` (404) / `ERR_METHOD_NOT_ALLOWED` (405) before any header check; trailing slashes tolerated; `GET /health` → `{status, clock}`, no headers — `app.py:43,69-96`
- §5 — insert — ambiguity — three uncatalogued rows added: `ERR_APPLICANT_INVALID_STATE` 409, `ERR_FACILITY_INVALID_STATE` 409 (after `ERR_DISASTER_INVALID_STATE`), `ERR_DEOBLIGATION_INVALID_STATE` 409 (after `ERR_DEOBLIGATION_NOT_FINAL`) — `errors.py:77-79`

Two internal PRD contradictions surfaced while doing this and were resolved in the implementation's favour: §2.9's blanket "every row touched has its version incremented" versus §2.4's conditional rule, and §2.5's "nothing reads the host wall clock" versus the response envelope's real-time timestamp.

### Orchestrator independent verification

`wc -l -c` confirms PRD.md 494 lines / 106,575 chars and PRD_COMPLETED.md 497 lines / 126,147 chars, matching the subagent's report exactly. Section headings are intact at lines 3/11/195/357/426 (same five `##` sections as the source — no new sections were added). The tail shows the §5 error table completing normally at the `ERR_NO_DOCUMENTED_COSTS | 409` row followed only by blank lines; the three new error ids appear 7 times total across §2.7/§3/§5. Ends at a real section boundary — not truncated.

## Pipeline complete — 2026-09-03T02:59:00.000Z

All nine steps finished. Step 8 was legitimately skipped (Step 7 green on first sweep, zero fixes); every other step produced its artifacts. Final state: 156/156 tests passing in all 8 rounds of the stability sweep, `workspace/PRD_COMPLETED.md` written.
