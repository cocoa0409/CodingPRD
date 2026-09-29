# Worklog — task_2507_false_alarm_reduction_alarm_permit_program

## Step 1: Create task directory — 2026-09-03T02:55:32.786Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2507_false_alarm_reduction_alarm_permit_program` and its `workspace/` subdirectory. Index 2507 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-03T05:56:00.000Z

Orchestrator note on execution shape: the first attempt spawned ONE subagent for all three
artifacts, per the skill's Step 2. It died with `API Error: Claude's response exceeded the
64000 output token maximum` after writing nothing — it tried to emit a 3000-line YAML in a
single tool call. Judgement call made autonomously (no user available): Step 2 was re-run as
THREE subagents — (2a) SCAFFOLD.yaml §1.0–§1.7, then (2b) SCAFFOLD_DIFFICULTY_DESIGN.yaml and
(2c) SCAFFOLD_CORNER_DESIGN.yaml launched concurrently since both only read SCAFFOLD.yaml —
each under a mandatory output-chunking instruction (first `Write` small, then append one
section per assistant message via `cat >>` heredoc, ≤600–800 lines per tool call). The
scenario text plus the "Generate task harder than expert level!" difficulty line were passed
verbatim to 2a; 2b/2c derive from SCAFFOLD.yaml. All three agents were given the
no-sibling-task-peeking constraint. Final three-file lint by the orchestrator: clean.

### Step 2a — SCAFFOLD.yaml (subagent summary, verbatim)

`SCAFFOLD.yaml` for task 2507 is complete and lints clean.

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_2507_false_alarm_reduction_alarm_permit_program/SCAFFOLD.yaml` (3,017 lines, single file; no other file created)

**Top-level keys (§1.0–§1.7 only):** scenario, domain_name (`false-alarm-reduction-permit-program`), api_prefix (`/false-alarm-program`), complexity_profile, response_envelope (verbatim), entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles. No `scaffold_difficulty_design` / `scaffold_corner_design`.

**Profile:** primary `compliance_audit` + secondary `pricing_engine`; layers `rate_threshold_triggers, cascading_side_effects, dual_variant_calculation, optimistic_concurrency`; topology `flat`; state-machine shape `cyclic`; relationships `one_to_many, self_referential, cross_aggregate, polymorphic`; role model `segregation_of_duties`; consistency `immediate`.

**Counts:** 15 entities · 11 state machines (75 transitions; PenaltyInvoice carries two independent dimensions `payment_status` + `collections_stage`) · 4 concurrency rules (all OCC/412 on AlarmSite ×2, PenaltyInvoice, AlarmSystem) · 16 calculations · 59 priority-ordered validations · 75 endpoints · 74 error codes · 8 roles.

**§0.5 coverage:** dual-variant (counting window ROLLING_365 vs PERMIT_YEAR; company score VOLUME_WEIGHTED vs PERIOD_EQUAL) · combinatorial modes a/b/c (`escalating_false_alarm_fee`, `invoice_assembly`, `delinquency_escalation`) · non-linear machines (incident APPEALED↔COUNTED/remand cycle, permit renewal cycle, report correction cycle, invoice two-axis) · cascades (`appeal_grant_cascade` depth 4, `unpermitted_cascade` depth 3) · 3 documented priority pairs (state>safety on `POST /dispatch-requests`; constraint>fiscal on permit renewals; temporal>constraint on `POST /appeals`) · boundary precision (strict `>` fee cap vs inclusive thresholds, clamped admin fee, round-per-line) · cross-entity state deps (site posture + company status gate dispatch) · two overlap rules with different interval semantics (docket half-open+15min buffer vs suspension closed/zero-buffer) · two compensating invariants (money conservation, contiguous chargeable-index conservation).

**Verdict:** `scaffold_lint.py` (with /tmp stubs for the two sibling design files) → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5`; 75 endpoints / 15 entities recognized. `yaml.safe_load` parses.

**Self-audit fixes applied beyond the linter:** every path referenced in §1.2/§1.2.1/§1.3/§1.4 resolves to a declared §1.5 endpoint; every transition `actor:` is in that endpoint's `roles:`; no unreachable or non-terminal-sink states (Appeal `REMANDED` made terminal); all 74 error ids cross-reference; each OCC endpoint takes `expected_*_version` as a required input and bumps the parent version; one leftover forbidden concurrency word ("simultaneously") removed; §1.4 field names reconciled to §1.1 (added `DispatchRequest.validated_by_user_id` and `PaymentRecord.recorded_by_user_id` to support the segregation-of-duties rule); APPEALED incidents now stay in the chargeable set so the occurrence-index sequence remains contiguous.

### Step 2b — SCAFFOLD_DIFFICULTY_DESIGN.yaml (subagent summary, verbatim)

`SCAFFOLD_DIFFICULTY_DESIGN.yaml` is complete for task_2507.

File: `/home/ubuntu/github/CodingPRD/tasks/task_2507_false_alarm_reduction_alarm_permit_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (261 KB, single top-level key — `python3 -c "print(list(d))"` → `['scaffold_difficulty_design']`).

Per-rule instance counts (all §0.5 rules covered, ≥2 each, no stubs/TODOs):
- `dual_variant_calc` — 4 (rolling-365 vs permit-year occurrence index; VOLUME_WEIGHTED vs PERIOD_EQUAL company score)
- `combinatorial_formula` — 3 (single-rounding of the full factor product; admin-fee ceiling clamp ordering; late penalty before the collections tier lookup)
- `non_linear_state_machine` — 3 (APPEALED→COUNTED denial rethaw; APPEALED→UNDER_REVIEW remand; PAID reached while dunning still reads FINAL_NOTICE)
- `transitive_cascade` — 2 (permit expiry → unpermitted → penalty → sibling-permit block; granted appeal → renumber → reprice → order vacatur)
- `priority_pair_validation_conflict` — 3 (p26 vs open-dispatch-request; no-active-fee-schedule vs renewal block; appeal-window-closed vs appeal-already-pending)
- `boundary_precision_check` — 4 (strict per-incident cap at exactly the cap; inclusive probation threshold; distinct-ECV-contact minimum off by one; day 89 vs day 90 referral)
- `cross_entity_state_dependency` — 3 (sibling-system dispatch gated by the site's suspension order; unrelated permit invoice blocking `/lift`; company suspension blocking validation but not an already-VALIDATED dispatch)
- `resource_temporal_overlap` — 4 (docket touching-boundary + cancellation frees; exact 15-minute buffer both sides; closed-interval suspension overlap incl. containment; free one day after, and again after `/vacate`)
- `compensating_invariant` — 2 (money conservation: 20000 AUTO_WATERFALL → void on the inclusive last legal day restores `0 == 0 + 0`; chargeable-count conservation: REMAND of the middle incident yields count 2, index set exactly {1,2}, I3 re-priced 30000→20000 / invoice 31500→21000, 21000 returned as un-consumed credit, outstanding 48000)

Total: 28 instances across 9 rules.

Linter: `python3 scaffold_lint.py <SCAFFOLD.yaml> <SCAFFOLD_DIFFICULTY_DESIGN.yaml> <SCAFFOLD_CORNER_DESIGN.yaml>` → `VERDICT: clean lint` (75 endpoints, 15 entities, 28 §1.8 instances + 127 §1.9 instances, 2941 calls scanned; all FKs reverse-reachable). The sibling corner file already existed in the task dir, so the real three-file lint ran — no /tmp stub needed, and no file other than mine was touched.

One fix worth flagging: `POST /appeals` requires `expected_false_alarm_incident_version`, which the remand instance initially omitted; it now passes the freshly captured `${inc_rm2_v}`.

### Step 2c — SCAFFOLD_CORNER_DESIGN.yaml (subagent summary, verbatim)

Done. `SCAFFOLD_CORNER_DESIGN.yaml` is complete and lint-clean.

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_2507_false_alarm_reduction_alarm_permit_program/SCAFFOLD_CORNER_DESIGN.yaml` (10,011 lines, single top-level key `scaffold_corner_design`)

Per-section instance counts (the nine sections of `references/claim-extraction-guide.md`):

| § | section | instances |
|---|---|---|
| 1 | entities | 17 |
| 2 | state_machines | 20 |
| 3 | calculations | 30 |
| 4 | validations | 60 |
| 5 | endpoints | 29 |
| 6 | errors | 13 |
| 7 | rbac | 28 |
| 8 | cross_cutting_complexity_layers | 16 |
| 9 | consistency_model | 2 |

**Total: 215 instances / 3,778 API calls, all 215 names unique.**

Coverage notes:
- Layer §8 breaks down as 8 `optimistic_concurrency` (one per §1.2.1 `concurrency_rules` entry plus stale-permit/incident/docket and a version-increment sweep), 3 `rate_threshold_triggers` (probation flip at the inclusive 4th, auto-proposal at the 6th, rolling-window reset), 2 `cascading_side_effects` (4-level determination chain; appeal-grant reversal), 3 `dual_variant_calculation` (counting-window ROLLING_365 vs PERMIT_YEAR divergence, capped vs uncapped assessment with a 40000 not 52500 delta, ECV two-attempts-one-contact vs exactly-two-distinct).
- §9 `immediate`: cascade hops visible in the writing response; no denormalised counter lags (3 counters on 3 parents, first-read correctness).
- Error triggerability: all 74 real `ERR_*` codes from §1.6 appear somewhere in the design (the only unmatched token is the spec's own `ERR_XXX` template placeholder).
- No TODO/placeholder/stub text anywhere in the file.

**Final linter verdict** (`scaffold_lint.py` with SCAFFOLD.yaml + a throwaway `/tmp/SCAFFOLD_DIFFICULTY_DESIGN.stub.yaml` + my file):

`VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

`python3 -c "... print(list(d))"` prints exactly `['scaffold_corner_design']`. No other file in the task directory was written or modified; the sibling `SCAFFOLD_DIFFICULTY_DESIGN.yaml` was never touched and no sibling task was read.

### Step 2 — orchestrator verification

Re-ran the three-file lint against the FINAL state of all three files (2b's and 2c's own lint
runs each raced a partially-written sibling, hence their differing §1.9 counts of 127 vs 215):

```
§1.5 endpoints declared:    75
§1.1 entities declared:     15
§1.8 instances scanned:     28
§1.9 instances scanned:     215
Calls scanned (§1.8+§1.9):  4569
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Line counts: SCAFFOLD.yaml 3017 · SCAFFOLD_DIFFICULTY_DESIGN.yaml 2147 · SCAFFOLD_CORNER_DESIGN.yaml 10011. All three `yaml.safe_load` cleanly and the two design files each expose exactly their single required top-level key.

## Step 3: Copy shared files — 2026-09-03T05:57:39.671Z

Copied `./INSTRUCTION.md` → `tasks/task_2507_false_alarm_reduction_alarm_permit_program/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T06:16:00.000Z

Doc-generator subagent was given SCAFFOLD.yaml only; both design indices were explicitly
withheld, as was the "Generate task harder than expert level!" difficulty line (that line went
to Step 2 alone and must never reach the PRD). The same output-chunking instruction from Step 2
was applied, plus an explicit anti-truncation gate (append one section per message, then
`tail -40` self-check), because the doc generator is known to silently drop trailing sections
on large PRDs.

### Subagent summary (verbatim)

PRD generated and verified.

**Artifact:** `/home/ubuntu/github/CodingPRD/tasks/task_2507_false_alarm_reduction_alarm_permit_program/workspace/PRD.md` — 542 lines, 140,805 bytes.

**Sections:** 1 Introduction; 2 Global Specifications (2.1 Actors/Access Control, 2.2 Response Structure [verbatim], 2.3 Pagination, 2.4 Identity/Timestamps/Revisions, 2.5 Path Resolution, 2.6 Logical Clock & Nightly Run, 2.7 Money/Counts/Rounding, 2.8 Stale-Revision Guards, 2.9 Governing Fee Schedule, 2.10 Order of Rejection, 2.11 Segregation of Duties); 3 Business Logic (3.1 Fee Schedules, 3.2 Premises/Contacts, 3.3 Registration & Permit Term Cycle, 3.4 Dispatch & ECV, 3.5 Determination/Counting/Escalating Fee, 3.6 Appeals & Hearing Calendar, 3.7 Suspension & Reinstatement, 3.8 Assessment/Dunning/Referral, 3.9 Payments/Allocation/Reversal, 3.10 Monitoring-Company Reporting); 4 Endpoint Definitions; 5 Error Code Catalogue.

**Coverage (mechanically checked against SCAFFOLD.yaml):**
- Endpoints: 75/75 exact `method + path` rows present in §4 (0 missing).
- Error codes: 74/74 in the §5 table, and 74/74 also raised by name in §2/§3 narrative.
- Validations: 59/59 stated in §2.10 in priority order, with priority pairs A/B/C called out as explicit collisions.
- Calculations: 16/16 with formula, rounding, clamping, pinned step order and variants (per-line-then-sum, admin-fee clamp, penalty-before-tier, tier boundary, VOLUME_WEIGHTED vs PERIOD_EQUAL, ROLLING_365 vs PERMIT_YEAR).
- State machines: 11/11, all 75 transitions plus the 4 §1.2.1 concurrency rules (and the 3 state-precondition version guards).
- Entities: 15/15 with fields; field-name coverage script: 266/266 scaffold identifiers (entity fields, endpoint inputs, path params, nested object keys) appear verbatim in backticks — 0 missing.
- RBAC: §2.1 narrative for all 8 roles (6 opaque, 2 entity-backed) + exhaustive Authorized Role(s) column on all 75 §4 rows. Per the skill, §4 is 4-column and §5 is 2-column, so per-endpoint request/response shapes and trigger conditions live in §2/§3 prose rather than in the tables.
- Contract 3 (§3 path purity): 0 violations — no backtick token in §3 starts with `/`, is a bare HTTP method, or combines method+path; zero raw `/false-alarm-program` occurrences in §3.
- §2.2 block byte-identical to `section-2.2-response-structure.md`; no fuzzy words, no race/simultaneity framing, no §1.8/§1.9 leakage.

**Tail check:** file ends at the final §5 row `| ERR_ALLOCATION_MISMATCH | 422 |` with a trailing newline — clean section boundary, no audit footer.

Isolation honored: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened or grepped, and no sibling task directory was read.

### Step 4 — orchestrator verification (truncation + leak gate)

- `wc -lc` → 542 lines / 140,805 bytes (long prose paragraphs, hence few lines for the size).
- `head -20` starts at `# False Alarm Reduction Permit Program API — Product Requirements Document`.
- `tail -25` ends on the error-catalogue row `| ERR_ALLOCATION_MISMATCH | 422 |` — a real section
  boundary, NOT mid-sentence. No regeneration needed.
- Leak grep for `harder than expert|expert level|scaffold|test_recipe|difficulty_design|corner_design`
  → zero hits. The Step 2 difficulty instruction did not reach the PRD.
- Independent coverage re-check by the orchestrator, parsing SCAFFOLD.yaml and grepping PRD.md:
  endpoints 75/75 present (0 missing), error ids 74/74 present (0 missing). Matches the
  subagent's own report.

## Step 5: Generate unit tests — 2026-09-03T07:05:00.000Z

Launched in the SAME assistant message as Step 6 (skill requirement): concurrency is what gives
the impl generator physical isolation from `test_suite/`, since the directory does not exist yet
when it starts. Test agent got SCAFFOLD + both design indices + PRD; it was explicitly barred
from reading `workspace/implementation/`. Output-chunking instruction carried over from Step 2.

### Subagent summary (verbatim)

Test suite generation for task_2507 is complete.

**Infrastructure — `test_helpers/` (2,675 lines, 9 modules)**
`types.py` 622 · `fixtures.py` 814 · `api_client.py` 403 (one method per PRD route) · `assertions.py` 216 · `factories.py` 193 · `api_errors.py` 172 (all 74 error ids + id→HTTP-status map registered with the framework) · `constants.py` 104 · `test_users.py` 93 · `__init__.py` 58. Plus `test_suite/conftest.py` (15).

**Tests — `test_suite/`, 267 tests in 14 thematic files (15,983 lines)**
validations_business_rules 30/1916 · validations_auth_and_occ 30/1435 · rbac 28/1837 · endpoints 26/1819 · state_machines 19/1123 · entities 17/892 · calculations_money 16/1040 · cross_cutting 16/1302 · difficulty_state_machine_cascade_priority 16/1238 · errors_and_consistency 15/593 · calculations_fees 14/845 · difficulty_boundary_and_cross_entity 14/1145 · difficulty_dual_variant_and_formula 14/819 · difficulty_overlap_and_invariant 12/1018.

**Coverage**
- Queue A (Difficulty): **28 / 28** instances translated, 2 tests each (56 tests).
- Queue B (Corner): **211 / 215** instances translated (211 tests).
- 239 distinct `Design:` tags = 28 + 211, exactly matching the two indices.

**Skipped instances (4, all PRD-first filter failures)**
- `state_machines/alarm_system_decommission_expires_its_active_permit` — instance asserts the permit becomes `EXPIRED`; PRD §3.3 states decommissioning drives it to `REVOKED`. Outcome not PRD-derivable.
- `endpoints/fee_schedules_list_filtered_to_active_excludes_the_superseded_row` — PRD §4 names no `status`/`schedule_code` filter on that listing.
- `endpoints/site_contacts_list_filtered_by_callable_flag_counts_only_reachable_rows` — PRD names only "filterable by premises"; `is_ecv_callable` is not a declared filter.
- `endpoints/false_alarm_incidents_list_filtered_by_occurrence_window_narrows_the_range` — `occurred_from`/`occurred_to` are declared for dispatch requests only.

**Mechanical self-checks (all pass)**
- (a) `python3 -m compileall` clean on both `test_helpers/` and `test_suite/`; `pytest --collect-only` collects all 267 with zero import errors.
- (b) 267/267 test docstrings end with exactly one `Design:` line (AST-verified as the last line; no untagged, no dual-tagged).
- (c) 0 unresolved tags — every instance name matches a `name:` scalar in the corresponding yaml byte-for-byte.
- (d) No `pytest.mark.skip`, `xfail`, `TODO` or `FIXME` anywhere. No duplicate test function names; nothing references `workspace/implementation/`.

**One helper defect found and fixed:** `fixtures.request_reinstatement` omitted the `corrective_action_summary` that PRD §3.7 requires (else `ERR_ECV_ATTESTATION_REQUIRED`); it now sends a non-empty default and accepts overrides.

**Design-index defects worth reconciling upstream** (translators asserted the PRD-derived value in each case): several instances compute `lifetime_assessed_cents`/`outstanding_balance_cents` while omitting the 5500-cent permit-issue invoices; `payment_allocation_row_…` asserts `sequence_index == 0` against the PRD's 1-based index; a few recipes place chargeable incidents inside `new_installation_grace_through`, and a few use undeclared enum values (`USER_ERROR`, `PROCEDURAL_DEFECT`, `NOT_A_FALSE_ALARM`). Also a genuine PRD tension: §3.3's renewal paragraph says `ERR_SITE_BALANCE_DELINQUENT` where §2.10 position 55 and Collision B say `ERR_PERMIT_RENEWAL_BLOCKED`; the suite follows §2.10 as authoritative.

## Step 6: Generate implementation — 2026-09-03T07:05:00.000Z

Launched concurrently with Step 5 in one assistant message. Impl agent read only
INSTRUCTION.md + SCAFFOLD.yaml + PRD.md; barred from `test_suite/`, `test_helpers/`, and both
design indices.

### Subagent summary (verbatim)

Implementation complete and verified.

**Files** (`.../task_2507_false_alarm_reduction_alarm_permit_program/workspace/implementation/`, 4599 lines total):

| file | lines | file | lines |
|---|---|---|---|
| engine.py | 812 | routes/reports.py | 179 |
| core.py | 429 | rt.py | 158 |
| routes/appeals.py | 293 | store.py | 156 |
| routes/dispatch.py | 270 | routes/invoices.py | 139 |
| routes/suspensions.py | 251 | routes/dockets.py | 131 |
| calc.py | 246 | routes/permits.py | 119 |
| routes/systems.py | 234 | routes/companies.py | 118 |
| routes/incidents.py | 232 | routes/contacts.py | 111 |
| routes/payments.py | 227 | routes/sites.py / fee_schedules.py | 109 / 109 |
| errors.py | 106 | app.py | 66 |
| routes/allocations.py | 37 | routes/admin.py | 32 |
| routes/__init__.py | 24 | start.sh / requirements.txt | 10 / 1 |

**Endpoint diff:** `PRD rows: 75  routed: 75  missing: []  extra: []` — full parity with PRD §4 (Flask `url_map` minus `/static`).

**Verification:**
- `python3 -m compileall -q .` → clean.
- Boot via `PORT=... bash start.sh` (foreground, binds 0.0.0.0, reads `$PORT`): unauthenticated `POST /alarm-sites` → `ERR_MISSING_AUTH_HEADERS` / HTTP 401 in the §2.2 error envelope; authenticated create → HTTP 201 with `response_type:"object"`, `created_at:"2026-08-01T00:00:00.000Z"` (logical clock), full derived premises row; unknown route → `ERR_RESOURCE_NOT_FOUND` / 404; list envelope carries `limit/offset/total_count/has_more`. Servers killed afterwards; no stray listeners, no `.json`/`.db`/`.sqlite` artifacts — storage is dicts only, zero seeding.
- Extra end-to-end driver (75-endpoint sample flow: schedule publish/activate → site/company/contacts → 4 systems + registration approvals → permits + issue-fee invoices → clock moves → 4 dispatch/validate/dispatch/incident/determination cycles → appeal file/docket/hold/grant with re-number + re-price cascade → payment waterfall + void → nightly run → compliance report file/review) — **0 failures**, fee ladder escalates correctly (index 3 → 10000+admin = 10500, index 4 → 25000+admin = 26250), and granting the appeal on the top occurrence removed exactly 26250 from the premises balance while re-numbering left occurrence 3 priced at 10500.

**One change made during verification:** `core._meta()` was stamping `api_request_timestamp` from `datetime.now()`. PRD §2.9 says "Nothing in this program consults wall-clock time", so it now reads the logical clock (`iso(now())`) — confirmed to follow `_clock/set_current_utc`.

**PRD detail worth flagging for the test suite:** the fee-schedule tier arrays use `fee_tiers[].from_index`/`to_index` (PRD §3.1/§3.5) and `late_renewal_tiers[].max_days_late` (§3.1/§3.3) — not `from_occurrence`/`to_days`. A fixture using the wrong keys silently yields tier base 0 (no match → 0), which is exactly the PRD-specified marginal lookup, not a bug.

## Step 7: Run tests and iterate — 2026-09-03T08:15:00.000Z

One long-lived diagnostic subagent owned the whole loop. It was given the setsid-nohup sweep
wrapper verbatim (unwrapped background rounds get SIGTERMed by any foreground Bash call and the
resulting RemoteDisconnected/ConnectionResetError looks exactly like a flaky implementation), the
CPU-contention caveat for this 32-pipeline host, and the three upstream leads reported by the
Step 5/Step 6 generators.

### Subagent summary (verbatim)

Clean sweep. All 8 parallel rounds: **267/267 passed, 0 failed, 0 errors, 0 skipped** (~567 s each).

## Iterations

3 full 8-round sweeps: #1 = 207/267 (60 failures, identical in all rounds); #2 = 261/267 (6 failures, identical); #3 = **267/267 in all 8 rounds**. Zero flakiness observed in any sweep — every round agreed exactly, so no load-induced noise to discount.

## Tests deleted

**None.** No test was PRD-silent at the whole-test level. Five *assertions* were removed or relaxed under STEP 1b/1c (partial coverage / silence), each with a citing comment left in place:

| Test | Assertion | Pattern |
|---|---|---|
| `test_corner_validations_auth_and_occ.py` | `schedule["activated_at"] == ...` → `version` comparison | COMPUTED-FIELD SILENCE — `activated_at` has **zero** occurrences in PRD.md |
| `test_corner_endpoints.py` | `withdrawn["hearing_docket_id"] is None` removed | BRANCH-ASYMMETRIC SIDE EFFECT — PRD §3.6 clears it on docket *cancellation* only; withdrawal names only the seat decrement + reopen |
| `test_corner_entities.py::test_dispatch_request_rejects_system_monitored_by_a_different_company` | → `validate_error_is_one_of([ERR_COMPANY_NOT_SYSTEM_MONITOR, ERR_NOT_RESOURCE_OWNER])` | ERROR PRECEDENCE SILENCE |
| `test_corner_rbac.py::test_alarm_company_operator_cannot_lodge_a_dispatch_for_another_companys_system` | same relaxation (reverse order) | ERROR PRECEDENCE SILENCE |
| `test_difficulty_state_machine_cascade_priority.py` + `test_difficulty_overlap_and_invariant.py` (remand tests) | `assessed_fee_cents` → `in (None, 0)` | DEFAULT-VALUE SILENCE — §3.6 says only "cleared"; the two tests contradicted each other (0 vs null) |

All sibling assertions in those tests were kept (no row created, lifetime count 0, follow-up 201, invoice VOIDED, allocation REVERSED, credit 5000, window count 2, contiguous index set).

## Fixes to `test_helpers/`

- `/…/test_helpers/fixtures.py` — `parse()` / new `same_instant()`: tolerate both `Z` and `.000Z` renderings, so tests comparing a server-computed instant to a literal stop depending on fractional-digit formatting. Also `create_contacts()` seeds `contact_priority` 1..count (PRD §3.2 uniqueness), and `orders_of_site()` lists **all** statuses via `per_page=100` so auto-proposed orders are visible.
- `/…/test_helpers/factories.py` — `contact_priority = ((n-1) % 5) + 1`, keeping generated rosters inside the PRD's priority domain.

## Fixes to `test_suite/` (test bugs, STEP 2)

`test_corner_rbac.py`, `test_corner_validations_business_rules.py` (7× bare `"2026-08-01"` → full `…T00:00:00Z` instants; `contact_priority=7`→`3`; `system_type="PANIC"`→`"HOLDUP_PANIC"`; 3 WAIVE payloads given the required `amount_cents`); `test_difficulty_state_machine_cascade_priority.py` (3× expected permit status `RENEWAL_DUE`→`RENEWAL_BLOCKED`, per §2.10 pos 55); `test_corner_calculations_fees.py`, `test_difficulty_dual_variant_and_formula.py`, `test_difficulty_boundary_and_cross_entity.py`, `test_difficulty_overlap_and_invariant.py` (instant comparisons routed through `same_instant`/`parse`).

`test_corner_cross_cutting.py::test_stale_alarm_site_version_blocks_a_second_suspension_order` — fixture built only 3 counted incidents while `suspension_threshold_count` defaults to **6**, so the *first* order was correctly refused with `ERR_SUSPENSION_BASIS_NO_LONGER_MET`. Rewritten to 6 systems / 6 counted incidents, with the hand-drafted intervals moved clear of the auto-proposed 2026-09-30…2026-10-30 order and the final count assertion made relative (`orders_before + 1`). The implementation's basis check was left intact.

## Fixes to `implementation/`

| File · function | Why |
|---|---|
| `engine.py::active_schedule` (+ new `active_status_schedule`) | PRD §2.9/§2.10 pos 43 gate money on a schedule being "`ACTIVE` **at the logical clock**", and §3.1 calls `effective_from` "the instant it governs from" — a future-dated activation governs nothing yet. This is what made Collision B (`ERR_NO_ACTIVE_FEE_SCHEDULE` outranking `ERR_PERMIT_RENEWAL_BLOCKED`) resolve correctly. Supersession, `company_thresholds`, and exempt-code lookups were repointed at the status-only helper so at most one row stays `ACTIVE`. |
| `engine.py::count_chargeable_in_window` | Dropped an `occurred > at` exclusion that shrank the window count. |
| `engine.py::recompute_outstanding` / `void_invoice_cascade` | A `VOIDED` invoice keeps `assessed_cents` for audit but holds `outstanding_cents` at 0 and is idempotent on re-void. |
| `engine.py::recompute_flagged_run` / `rollup_company` | §3.10 makes `consecutive_flagged_report_count` a *stateful* counter (incremented on flag, reset on accept and on PROBATION→ACTIVE); only registration derives it from the report history. |
| `routes/reports.py::review_report` | Applies that increment/reset on review. |
| `routes/companies.py` (registration) | Derives the flagged run at creation per §3.10. |
| `routes/incidents.py::determine_incident` | `assessed_fee_cents` starts null on create; the three COUNTED preconditions hoisted above the `REPORTED→UNDER_REVIEW` mutation so a refused ruling leaves the incident untouched (§2.10: rejection precedes effect); EXEMPT branch pins `occurrence_index=null`, `assessed_fee_cents=0`. |
| `routes/appeals.py` | `APPEALED` accepted as a declared source for a further filing so Collision C (window pos 30 beats pending-appeal pos 36) can be reached; remand *clears* `assessed_fee_cents`. |
| `routes/dispatch.py::create_dispatch_request` | Position 8 identity check ordered ahead of the position-22 coherence check. |

## Leads for Step 8 — three PRD internal contradictions

1. **§3.3 vs §2.10 pos 55 / Collision B** — the renewal paragraph names `ERR_SITE_BALANCE_DELINQUENT` where the order-of-rejection table and Collision B name `ERR_PERMIT_RENEWAL_BLOCKED`.
2. **§3.4 vs §2.1 / §2.10 pos 8** — dispatch submission by a non-monitoring `AlarmCompanyOperator` is assigned `ERR_COMPANY_NOT_SYSTEM_MONITOR` (409) by §3.4 and `ERR_NOT_RESOURCE_OWNER` (403) by §2.1, with §2.10 ranking the identity check first. Two generated tests pinned opposite codes for byte-equivalent scenarios.
3. **§3.6 remand** — `assessed_fee_cents` is only "cleared", leaving 0-vs-null undetermined, while §3.5's exempt branch and §3.6's grant both say explicitly "0". Again, two generated tests pinned opposite values.

### Step 7 — orchestrator verification (sweep-artifact gate)

A Step 7 subagent can report a clean sweep while leaving no usable artifacts, so the orchestrator
re-checked the on-disk evidence rather than trusting the report:

- All 8 `workspace/implementation/results.{1..8}.json` exist (~81.8 KB each, all written 08:11)
  and every one parses to `passed=267 failed=0 errors=0 skipped=0 total=267`. Genuine 8/8 clean.
- `grep -rn "mark.skip|mark.xfail|TODO|FIXME" test_suite/ test_helpers/` → zero hits. No test was
  dodged rather than fixed.
- Collected test count still 267 — consistent with the subagent's "no tests deleted" claim
  (only five individual assertions were relaxed/removed under STEP 1b/1c).
- `find` for `*.db`/`*.sqlite*`/`*.pkl` under `workspace/implementation` → nothing; grep for
  `sqlite3|open(...'w'|json.dump(|pickle` → nothing. Storage is in-memory dicts only and no
  entity data is seeded at startup, so per-test-server isolation really does wipe all state.

Step 7 made 8 `implementation/` fixes, so Step 8's skip condition does NOT apply — Step 8 runs.

## Step 8: Finalize PRD — 2026-09-03T08:35:00.000Z

Not skipped: Step 7 applied 8 `implementation/` fixes, so the zero-iteration skip condition did
not hold. The Step 7 worklog entry (deletions/relaxations, test_helpers fixes, test_suite fixes,
implementation fixes, plus its three "PRD internal contradiction" leads) was inlined verbatim as
`<step_7_diff>`. The subagent was barred from SCAFFOLD*.yaml and worklog.md, and was told to
`cp` then make each edit as a small targeted `Edit` call rather than rewriting the 141 KB file in
one tool call (the 64k output cap already killed one agent in this pipeline).

### Subagent summary (verbatim)

`workspace/PRD_FINALIZED.md` is complete.

## Size

| | PRD.md | PRD_FINALIZED.md | delta |
|---|---|---|---|
| lines | 542 | 546 | +4 (+0.74%) |
| bytes | 140,377 | 147,000 | +6,623 (+4.72%) |

17 paragraphs touched (2 of them paragraph inserts); headers 29→29 and table rows 153→153 unchanged.

## Changes

- §2.4 Common shape — revise + insert — `created_at` no longer promises "three fractional digits"; a new paragraph pins that a client-supplied instant (write body, or the string the clock was last set to, which is every "at the logical clock" stamp) is echoed verbatim, while a server-derived instant renders as ISO 8601 UTC with three digits, and comparisons are always on the instant — `core.py:Instant/_jsonable`, `store.py:iso/set_clock`
- §2.9 ¶1 — revise + insert — "at most one schedule is `ACTIVE`" restated as a status claim, plus a paragraph distinguishing `ACTIVE`-at-the-clock from `ACTIVE`-by-status and naming the three status-only readers (supersession, company thresholds, exempt-code recognition) — `engine.py:29,41,76`, `routes/fee_schedules.py:86`, `routes/incidents.py:115`, `routes/appeals.py:179`
- §2.9 ¶3 — revise — the clock test guards registration approval and renewal only; chargeable determination is guarded by pinning instead and does not re-test the clock; other pinned-constant consumers answer the same code when unpinned — `routes/incidents.py:150`, `routes/systems.py:123`, `routes/permits.py:46`, `routes/invoices.py:99`
- §2.10 position 43 — revise — same split (clock-active on approval/renewal, pinned on determination) so the priority row stops claiming a single universal test — `routes/incidents.py:150`
- §2.10 positions 22–24 — revise — `ERR_COMPANY_NOT_SYSTEM_MONITOR` keeps its position and 409, but is shadowed on all three operations by the position-8 identity check, which reports `ERR_NOT_RESOURCE_OWNER` — `routes/dispatch.py:93-95`, `core.py:205-214`
- §3.3 Renewal — revise — a renewal blocked by `renewal_block_active` yields `ERR_PERMIT_RENEWAL_BLOCKED`, except from `GRACE`, which yields `ERR_SITE_BALANCE_DELINQUENT` — `routes/permits.py:52-58`
- §3.4 Submission gates — revise — the monitor-mismatch refusal a submitter actually sees is `ERR_NOT_RESOURCE_OWNER` — `routes/dispatch.py:91-96`
- §3.5 Incident creation — revise — `occurrence_index` and `assessed_fee_cents` are null (not 0), along with `determination`, `exempt_cause_code`, `determined_at`, `determined_by_user_id`, `fee_basis`, `counted_window_mode` — `routes/incidents.py:80-88`
- §3.5 Determination — revise — every check precedes the `REPORTED → UNDER_REVIEW` hop, so a refusal leaves status, fields and `version` untouched — `routes/incidents.py:138-155`
- §3.5 Premises counters — revise — the two counters are bounded below only (an incident occurring after the clock still counts), `chargeable_count_permit_year` counts everything when no term contains the clock, and `chargeable_count_window` falls back to the rolling count when unpinned — `engine.py:222-231,425-434`
- §3.6 Filing — revise — declared source states are `COUNTED` **or** `APPEALED`; anything else fails position 17 with `ERR_INVALID_STATE`, and `APPEALED` is declared so Collision C is reachable — `routes/appeals.py:70-72`
- §3.6 `REMANDED` — revise — `fee_basis` is cleared too, and the cleared fields go to null, `assessed_fee_cents` to null rather than 0 — `routes/appeals.py:199-210`
- §3.6 Withdrawal — revise — withdrawal does not clear the appeal's `hearing_docket_id`; only docket cancellation does — `routes/appeals.py:250-277` vs `routes/dockets.py:101`
- §3.8 Adjustment — revise — `WAIVE`/`REDUCE` must carry `amount_cents` (absence → `ERR_MISSING_REQUIRED_FIELD`), `WRITE_OFF` takes none and is always exactly `outstanding_cents`, and the conditional check runs last, after segregation, revision and state checks — `routes/invoices.py:35-64`
- §3.9 Roll-up step one — revise — a `VOIDED` invoice holds `outstanding_cents` at 0 and is never recomputed — `engine.py:314-321`
- §3.10 Registration — revise — the report-history derivation is registration-only, with a creation-order tie-break; thereafter the counter is stateful (0 on `ACCEPT`, +1 on `FLAG_VARIANCE`, 0 on `PROBATION → ACTIVE`) and is untouched by corrections, status actions, reads, roll-ups and the nightly pass — `engine.py:541-553,564`, `routes/reports.py:112,117`, `routes/companies.py:59`
- §3.10 Filing a period — revise — the identity check is the whole coherence requirement; a filing does not return `ERR_COMPANY_NOT_SYSTEM_MONITOR` — `routes/reports.py:56-60`

## Pre-edit search log

1. **Instant rendering.** (a) how instant-valued fields are serialized. (b) `core.py` `Instant`/`parse_instant`/`_jsonable`/`_meta`/`_sortable`, `store.py` `iso`/`set_clock`/`base_row`/`add_days`, `routes/admin.py:set_current_utc`. (c) split the claim by provenance (client-echoed vs server-derived) instead of asserting three digits everywhere; added the explicit "comparisons are on the instant" clause since `_sortable` normalizes.
2. **Two senses of `ACTIVE`.** (a) what "`ACTIVE` schedule" means. (b) `engine.active_status_schedule`, `engine.active_schedule`, `engine.company_thresholds`, `engine.governing_schedule/require_governing`, `routes/fee_schedules.py:86`, `routes/incidents.py:115`, `routes/appeals.py:179`, `routes/permits.py:46,49`, `routes/systems.py:123`. (c) enumerated the status-only readers as a closed pair of *kinds* rather than a closed list of callsites, so future constant lookups are not mis-described.
3. **Money gate vs pinning gate.** (a) which test raises `ERR_NO_ACTIVE_FEE_SCHEDULE` where. (b) all four raise sites: `routes/systems.py:123`, `routes/permits.py:46`, `routes/incidents.py:150`, `routes/invoices.py:99`; plus `engine.require_governing`. (c) named the two clock-gated operations exhaustively but left the pinned-constant consumers open-ended ("a collections referral among them") because `require_governing` is a general helper.
4. **Position 43 wording.** (a) the priority row for the fee-schedule gate. (b) same four sites as (3); checked §3.3/§3.5/§3.7 prose for the old universal claim. (c) rewrote as "either test fails at this position" so one row still covers both tests without asserting they are the same test.
5. **Renewal block code.** (a) the code for a fiscally blocked renewal. (b) `routes/permits.py:40-58` (check order: version → state → grace → site → ECV → clock-active schedule → block), §2.10 pos 54-55, §2.10 Collision B, §3.3 grace loop, `routes/systems.py` new-issuance path (unchanged, `ERR_SITE_BALANCE_DELINQUENT`). (c) stated the general code first and the `GRACE` case as a named single exception, and cross-referenced the existing §3.3 grace sentence rather than duplicating it.
6. **Premises counters.** (a) the window bounds of the premises counters. (b) `engine.count_chargeable_in_window`, `engine.window_start`, `engine._permit_year_start`, `engine.recompute_chargeable_counts`, and readers `engine.derive_posture`, `engine.auto_propose_suspension`, `routes/suspensions.py`, `routes/appeals.py:234`; contrasted with `engine.occurrence_index_for`, which *does* bound above. (c) added "unlike the numbering window" so the edit cannot be read back onto the incident-indexing window, and stated both degenerate cases (no upper bound, missing term start) explicitly.
7. **Incident creation nulls.** (a) initial field values on a `REPORTED` incident. (b) `routes/incidents.py:73-90`, plus every other writer of those fields: `void_incident:203-205`, `appeals.py:199-210` (remand), `appeals.py:220-226` (grant, fee 0). (c) said "null — not 0" and listed the companion fields, while leaving the grant's explicit 0 untouched.
8. **Determination atomicity.** (a) whether a refused ruling persists the `UNDER_REVIEW` hop. (b) `routes/incidents.py:99-159` (no `touch` before any raise), `store.touch`, the two other writers of `UNDER_REVIEW` (`appeals.py:201`). (c) scoped the claim to "every check the ruling must pass" rather than to the endpoint as a whole, so the remand-driven entry into `UNDER_REVIEW` is unaffected.
9. **Appeal filing source states.** (a) the declared source states for a filing. (b) `routes/appeals.py:63-83` (owner → version guard → status → window → pending), §2.10 pos 17, Collision C at pos 30/36. (c) tied the `APPEALED` allowance to Collision C so the wording explains why rather than only asserting the pair.
10. **Remand field clearing.** (a) which fields a remand clears and to what. (b) `routes/appeals.py:199-217`; compared against grant hop one (`fee 0`, `exempt_cause_code` set) and `create_incident`. (c) contrasted null-vs-zero against the grant explicitly; deliberately said nothing about `exempt_cause_code`, which the remand does not touch.
11. **Withdrawal and the docket pointer.** (a) whether `hearing_docket_id` survives withdrawal. (b) `routes/appeals.py:250-277`, `routes/dockets.py` cancellation (clears it), `schedule_appeal:146` (sets it), nightly `DISMISSED_UNTIMELY` path in `engine.nightly_run` (never seated). Also checked `rt.py:69-73` — there is no `withdrawal_reason` column, so the existing "takes an optional `withdrawal_reason`" needed no change. (c) phrased the clearing as "a docket cancellation's act alone", which the nightly dismissal path does not contradict.
12. **Voided invoice outstanding.** (a) step one of the roll-up on a `VOIDED` invoice. (b) `engine.recompute_outstanding:314-321`, `engine.void_invoice_cascade`, `engine.settle_check` (also early-returns on `VOIDED`), `engine.rollup_site` steps 2 and 3, §3.7 cascade-void sentence. (c) marked it "the single exception" to step one and reused §3.7's existing "preserved for audit" framing to avoid two competing statements.
13. **Flagged-run counter.** (a) the lifecycle of `consecutive_flagged_report_count`. (b) grepped every occurrence: `engine.recompute_flagged_run:541`, its only caller `routes/companies.py:59`, `engine.rollup_company:564` (explicitly not recomputed), `routes/reports.py:112,117`, `engine.apply_company_status_from_score:599`, `engine.nightly_run:840,845` (reads only), `routes/companies.py:63-95` status actions (no reset), `get_company` (rolls up but not the run). (c) listed the movers as a closed set and the non-movers explicitly, and kept the existing "recomputed score and counters" read sentence true by naming what a read does refresh.
14. **Monitor-coherence code.** (a) whether `ERR_COMPANY_NOT_SYSTEM_MONITOR` is ever what a caller sees. (b) grepped the code across the tree — one raise only, `routes/dispatch.py:95`, preceded by `check_owner` at :93; `routes/incidents.py:61` and `routes/reports.py:60` use `check_owner` alone; `core.check_owner:205-214`; `routes/dispatch.py:27-36` (no independent `alarm_site_id` input) and `reports.py:23-30`. (c) avoided the absolute "never returned": the code keeps its position and 409, and the shadowing is justified by role plus single-reference structure — which is what makes it unobservable without asserting unreachability as a rule.
15. **§3.4 gate list.** (a) the same subject at the submission gate list. (b) `routes/dispatch.py:85-116` full gate order. (c) kept the gate in the list (it is still the position-22 condition) and named only the observed code, so the §2.10 ordering sentence following it stays true.
16. **§3.10 filing gate.** (a) the same subject at report filing. (b) `routes/reports.py:56-72`. (c) explained the absence structurally (the report names no system) rather than deleting the requirement, so the §2.10 row and this paragraph agree.
17. **Adjustment amount.** (a) the conditional requirement on `amount_cents` and its place in the order. (b) `routes/invoices.py:30-79` (SOD → version → `VOIDED` → `WRITTEN_OFF` → write-off stage → missing amount → outstanding comparison), §2.10 positions 8-10 (identity/SOD) and 11-16 (revision guards) — impl order matches, so no ordering edit was needed there. (c) added the "not tested at the field-validation positions" note with two concrete precedence examples, since without it a fresh implementer would reject at position 4.

Two step_7_diff items were deliberately left unpatched, with reasons: the `activated_at` relaxation (`routes/fee_schedules.py` never sets such a field and the PRD never names it) and the re-void idempotency guard in `engine.void_invoice_cascade` (unreachable, since `invoice_for_incident`/`invoice_for_order` filter `VOIDED` out). The remaining diff items — `RENEWAL_DUE` expectations, `contact_priority=7`, `system_type="PANIC"`, bare-date payloads, `orders_of_site` paging, and the stale-version fixture rewrite — were fixture bugs with no PRD counterpart.

### Step 8 — orchestrator verification

`wc -lc` → PRD.md 542 lines / 140,805 B, PRD_FINALIZED.md 546 lines / 147,472 B. `cmp` confirms
the two files differ (a byte-identical output would mean the pass never ran); `diff | wc -l` = 72.
Tail of PRD_FINALIZED.md still ends on the `ERR_ALLOCATION_MISMATCH` catalogue row — no truncation.

## Step 9: Complete PRD — 2026-09-03T09:30:00.000Z

Orchestrator decision (autonomous, no user available): Step 9 was run as THREE SEQUENTIAL
FILE-PARTITIONED PASSES over disjoint implementation file sets rather than one whole-impl scan.
Rationale: a single pass over a 4653-line implementation plus a 147 KB PRD reliably degenerates
into a no-op (the tell being PRD_COMPLETED.md coming out byte-identical to PRD_FINALIZED.md), and
this pipeline had already lost one agent to the 64k single-response output cap. Partition:
  - Pass 1 — infra + pure calculation: app.py, core.py, store.py, rt.py, errors.py, calc.py (1163 lines)
  - Pass 2 — domain engine: engine.py (849 lines)
  - Pass 3 — HTTP surface: all 17 routes/*.py modules (2486 lines)
Pass 1 bootstrapped PRD_COMPLETED.md from PRD_FINALIZED.md; passes 2 and 3 edited it in place and
were told not to revert a prior pass's sentence but to refine it. Each pass was allowed to read
the out-of-scope files as corroborating context (a helper's real contract is only visible at its
callsites) but not to scan them. Each pass carried the same no-false-universal-claim rule and the
same one-small-Edit-per-call chunking rule. Handoff items were passed forward explicitly.

### Pass 1 summary (verbatim) — infra + calculation layer

Pass 1 complete.

## Result
- `PRD_FINALIZED.md`: 546 lines / 147,472 chars → `PRD_COMPLETED.md`: 546 lines / 151,693 chars (**+4,221 chars**, no line-count change — all edits are in-paragraph). `cmp` differs; tail still ends at the `| ERR_ALLOCATION_MISMATCH | 422 |` row.
- **15 edits across 14 PRD lines: 11 ambiguity-pins, 4 mismatch-revisions.**

## Changes
- §2.1 (L23) — insert — ambiguity — ownership check passes when the target carries no reference of the acting role's kind; list reads confine an entity-backed caller by *filtering* (with `total_count` over the filtered set), with the hearing-docket list the one unfiltered exception — `core.py:205-214`, `rt.py:151-158` (corroborated `routes/dockets.py:117`)
- §2.2 (L48) — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from A–Z/0–9, minted on error responses too — `core.py:87-89`
- §2.2 (L49) — insert — ambiguity — the timestamp reads the *logical clock* and is always rendered with three fractional digits — `core.py:92-98`, `store.py:79-88`
- §2.2 (L51) — **revise** — **mismatch** — the two §2.6 admin operations answer 200 with `data` **null**, not an empty object — `core.py:132-134` / `routes/admin.py:25,32`
- §2.3 (L78) — insert — ambiguity — `page`/`per_page` accepted only as an optionally signed digit run after trimming (else `ERR_INVALID_PAGINATION`), empty value = absent; sort key read from `sort` else `sort_by`, leading `-` = descending; declared sort fields = entity columns + whichever common columns it carries (so no `version`/`updated_at` on `PaymentAllocation`) — `core.py:337-374`, `rt.py:9-102,125`
- §2.3 (L80) — insert — ambiguity — `created_at` ties broken by insertion order; explicit sort puts nulls last ascending and reverses the *whole* comparison (nulls first, reverse insertion order) under `-` — `core.py:377-387`, `store.py:143-145`
- §2.4 (L90) — **revise** — **mismatch** — the non-bumping recompute exception is not unique to the summary read: moving the clock also refreshes every premises without bumping its `version` — `store.py:133-140` (corroborated `engine.py:461,502`, `routes/admin.py:23`)
- §2.5 (L94) — insert — ambiguity — unrouted path and unrouted method both answer `ERR_RESOURCE_NOT_FOUND` at 404 (not 405); trailing slash is the same route — `app.py:28,37-44`
- §2.7 (L108) — insert — ambiguity — instant grammar: case-insensitive `T`/`Z`, 1–9 fractional digits, numeric offsets rejected — `core.py:42-44`
- §2.7 (L116) — **revise** ×2 — **mismatch** — day arithmetic is a floor toward negative infinity, not truncation toward zero; inspection freshness keeps its sign instead of clamping at 0 — `store.py:99-111` (callsite `routes/suspensions.py:156`)
- §2.10 (L149) — insert — ambiguity — booleans must be JSON `true`/`false`; undeclared fields ignored; absent/empty/unparseable/non-object body treated as `{}` so the first required field answers — `core.py:171-182,261-264,317-330`
- §3.3 (L221) — insert — ambiguity — late fee is 0 when no ladder entry covers the days late — `calc.py:168-177`
- §3.5 (L257) — insert ×2 — ambiguity — first covering `fee_tiers` entry in declared order wins and an uncovered index gives tier base 0; occupancy multiplier defaults to 1 for an unlisted class — `calc.py:36-57`
- §4 (L394) — **revise** — **mismatch** — fee-schedule list is not "newest effective instant first"; it uses the §2.3 default order and filters on status/schedule_code — `core.py:377-387`, `store.py:143-156` (callsite `routes/fee_schedules.py:100-111`)

## Deliberately left unpatched
- **`ERR_INTERNAL` / HTTP 500** (`app.py:51-55`): a defensive last-resort handler with no catalogue row. Adding a row would alter the §5 table tail I was told to preserve, and no declared operation reaches it.
- **Error catalogue**: verified programmatically — all 74 rows in §5 match `errors.py ERROR_STATUS` one-for-one on id *and* status, in the same order. No edit needed.
- **`core.plain()`** is dead code (no callers) — no PRD implication.
- Verified-and-already-pinned (no change): every `calc.py` formula — fee steps and single rounding, per-line rounding, admin-fee clamp, reinstatement escalation, collections tiers/boundaries, `period_metrics`, `company_score` (incl. zero-weight fallback and empty-set 1.00), docket 15-minute half-open buffer, closed-interval suspension geometry; the six `pct` fields match §2.7's list exactly; `AP-`/`INV-`/`RCT-%06d` formats and `CLOCK_START` are pinned already.

## For pass 3
`routes/sites.py:103-109` returns the **whole `AlarmSite` row** from `/false-alarm-summary`, while §4 (L402) describes a bespoke computed projection — that endpoint's file is pass-3 scope, so I left it.

### Pass 2 summary (verbatim) — domain engine (engine.py)

Pass 2 complete.

## PRD_COMPLETED.md size
- Before: **151,693 chars / 546 lines** → After: **157,215 chars / 546 lines** (+5,522 chars; no new sections, no new paragraphs — all inserts are in-paragraph)
- Tail verified: still ends at `| ERR_ALLOCATION_MISMATCH | 422 |`, not mid-sentence.

## Counts
17 edits: **14 ambiguity-pins, 3 mismatch-revisions**

## Changes
- §3.5 counting variants — insert — ambiguity — the `PERMIT_YEAR` numbering anchor is chosen from any permit whose closed term/grace interval contains the instant *whatever its current status*, and when no permit qualifies the window is bounded above only — engine.py:199
- §3.5 counting invariant — insert — ambiguity — renumbering re-assesses an existing invoice in place, voids it (allocations reversed into credit) when the re-derived fee falls to zero, and never issues an invoice that did not already exist — engine.py:412
- §3.5 counting invariant — insert — ambiguity — renumbering rewrites `counted_window_mode` from the governing schedule's current mode and bumps an incident's `version` only when `assessed_fee_cents` or `fee_basis` actually moved — engine.py:403
- §3.5 billing knock-on — insert — ambiguity — auto-proposed order's `suspension_sequence` / null frozen fields, and the proposal is silently suppressed when its computed interval collides with a `PROPOSED`/`EFFECTIVE`/`REINSTATEMENT_PENDING` order — engine.py:679
- §3.6 grant hop three — insert — ambiguity — re-assessment = subtotal + re-clamped admin fee + already-accrued `late_penalty_cents` (never refunded), and `adjusted_cents` is clamped down to assessed − paid — engine.py:376
- §3.6 untimely dismissal — revise — **mismatch** — "clock passes filed_at + 60 days" → whole days from `filed_at` must *exceed* 60, so dismissal lands on the 61st whole day — engine.py:824
- §2.6 nightly permits — insert — ambiguity — the three permit hops chain inside one pass (`ACTIVE`→`RENEWAL_DUE`→`GRACE`→`EXPIRED`) — engine.py:757
- §2.6 nightly close — insert — ambiguity — pinned phase order (permits, invoices, orders, appeals, sites, companies) with the observable consequence that a dismissal's unfrozen dunning waits for the next run; plus the two closing roll-ups bump `version` only when a rolled-up value moved — engine.py:744, 516
- §3.8 dunning ladder — insert — ambiguity — at most one dunning stage per invoice per run (the two steps are mutually exclusive) — engine.py:795
- §3.9 roll-up step six — revise — **mismatch** — "when the flag has just become true/false" → the step reads the flag's *current* value, not a transition, and so reconciles drifted permit statuses — engine.py:492
- §3.10 manual `REINSTATE` — insert — ambiguity — "consecutive" is measured within the `ACCEPTED` reports alone (interleaved flagged/submitted periods neither count nor break the run), `period_end` strict, 0.70 literal, no anchor ⇒ whole accepted history — engine.py:604
- §3.1 company thresholds — insert — ambiguity — read from whichever schedule holds `ACTIVE` status regardless of the clock, falling back to 0.70/0.50 when none does — engine.py:73
- §2.10 position 49 — revise — **mismatch** — `ERR_ACTIVE_PERMIT_EXISTS` set now includes `RENEWAL_BLOCKED` (matches §3.3 and `LIVE_PERMIT_STATUSES`) — engine.py:14
- §3.3 renewal — insert — ambiguity — the `chargeable_count_permit_year` reset is immediately re-derived by the closing roll-up from the new `term_start_at` (resolving an internal contradiction with §3.9 step four) — engine.py:425
- §3.8 assembly — insert — ambiguity — the free-allowance false alarm is the *only* suppressed row; every other kind issues even at a zero subtotal and still carries `admin_fee_min_cents` — engine.py:280
- §3.8 cascade void — insert — ambiguity — `paid_cents` drops by the total reversed and the parent payment records stay `APPLIED` with null `voided_at` — engine.py:356
- §3.10 status consequences — insert — ambiguity — a review bumps the company's `version` by exactly 1 regardless of movement and records `status_reason` as `COMPLIANCE_SCORE_REVIEW` — engine.py:573

## Deliberately left unpatched
- `recompute_flagged_run` at registration (engine.py:541) — reports cannot pre-date their own company, so it always yields 0; its ordering/reset semantics are unobservable and PRD's existing wording stands.
- `settle_check` using `>=` rather than `==` (engine.py:329) — paid can never exceed assessed (allocations cap at outstanding; `reassess_invoice` sweeps excess into credit).
- `unpermitted_cascade` billing a system that was not `PERMITTED`, and billing nothing when the premises is unpinned (engine.py:665) — both unreachable (one live permit per system; any premises holding a permit is pinned).
- `active_status_schedule` taking the earliest-created `ACTIVE` row (engine.py:35) — unreachable under the status-uniqueness invariant pass 1 already pinned.
- `price_incident` coercing a null index to 0 / a missing request to `{}` (engine.py:268) — unreachable via routes.
- `recompute_outstanding` firing on read-only roll-ups — cannot change a stored value on those paths, so nothing observable to pin.
- `derive_posture`'s unpinned-premises short-circuit (engine.py:438) — already pinned verbatim in §3.5.

## Pass-1 interaction
Nothing reverted. I *extended* two sentences that read as pass-1/original wording rather than contradicting them: §2.6's "bumps the `version` of every entity it mutated by 1" now carves out the two conditional roll-ups, and §3.1's threshold sentence now points at §2.9's clock-free constant-lookup rule (pass 1's own text) and adds the missing no-schedule fallback.

## Handoff for pass 3
`routes/suspensions.py:194-200` lets an invoice with `payment_status == "VOIDED"` pass the lift gate, while §3.7 states every non-written-off invoice "must have `payment_status` of `PAID`". That is a genuine mismatch but lives in pass 3's file set, so I left it alone — pass 3 should revise §3.7 to `PAID` or `VOIDED`.

### Pass 3 summary (verbatim) — HTTP surface (routes/)

Pass 3 of 3 complete.

## Exit verification
- **Char count:** 157,215 → **171,173** (grew by 13,958). **Line count: 546 → 546** (every edit was in-paragraph; no new sections, no new paragraphs).
- **Tail intact:** file still ends at `| \`ERR_ALLOCATION_MISMATCH\` | 422 |`, not mid-sentence.
- **§4 table:** still exactly **75** endpoint rows.
- **55 targeted `Edit` calls**, one sentence each — **36 ambiguity-pins**, **19 mismatch-revisions**. No file rewrite, no `cp`, no section replacement.

## Handoff items — both resolved
1. **`routes/sites.py:103-109` — CONFIRMED mismatch.** `site_summary` calls `engine.rollup_site(site, bump=False)` and then `return ok(site)` — the whole `AlarmSite` row, not a bespoke projection. §3.2 revised: the summary "returns the whole premises resource … in exactly the shape the single-premises read returns."
2. **`routes/suspensions.py:194-200` — CONFIRMED mismatch.** The gate skips any invoice whose `payment_status` is in `("PAID", "VOIDED")`. §3.7 revised to "`PAID` or `VOIDED`", and the net test relaxed to "not above zero" (impl compares `<= 0`, not `== 0`).

## Changes
- §2.1 — revise — mismatch — the "one unfiltered list" claim was false; an `AlarmCompanyOperator` also reads the contact list unfiltered — routes/contacts.py + rt.py `scope_reads`
- §2.3 — insert — ambiguity — global filter semantics: exact match, no case folding; every `*_from`/`*_to` is an inclusive bound on **one** instant field; a reporting-period window tests `period_start`; null window field excluded — routes/incidents.py:234, routes/reports.py
- §2.4 — revise — mismatch — read-recompute exemption generalized to every premises and company read; step-six permit reconciliation *does* bump the permit's own `version` — engine.py `rollup_site`
- §2.9 — insert — ambiguity — duplicate `schedule_code` → `ERR_INVALID_FIELD_VALUE` — routes/fee_schedules.py:60
- §2.9 — insert — ambiguity — a fresh issuance takes `permit_term_days`/`renewal_grace_days` from the **ACTIVE** schedule even at a pinned premises; money and the delinquency threshold come from the pinned row — routes/systems.py:121
- §2.10 — revise — mismatch — `ERR_INCIDENT_ALREADY_REPORTED` fires on a prior incident of any status, a `VOIDED` one included — routes/incidents.py:66
- §2.10 — revise — mismatch — roster minimum is a flat 2, never posture-varying; only §3.7's reinstatement order demands more — routes/dispatch.py `ECV_MINIMUM`, systems.py:114, permits.py:42
- §3.2 — revise — mismatch — `address_key` is stored raw; normalization is comparison-only — routes/sites.py:57
- §3.2 — insert — ambiguity — empty/whitespace `address_key` → `ERR_INVALID_FIELD_VALUE`; the list filter is normalized — core.py `_coerce`, sites.py:89
- §3.2 — revise — mismatch — **handoff 1**: summary returns the whole premises row — routes/sites.py:103
- §3.2 — insert — ambiguity — roster removal tests the count that *would remain* — routes/contacts.py
- §3.3 — revise — mismatch — `installed_at` is recorded only; it is not the grace anchor — routes/systems.py
- §3.3 — insert — ambiguity — archived premises → `ERR_INVALID_STATE`; block threshold read pinned-else-active — routes/systems.py:107,125
- §3.3 — insert — ambiguity — approval answers 201 with the created permit — routes/systems.py:164
- §3.3 — insert — ambiguity — patch fields all optional; gate is SUBMITTED/PERMITTED/UNPERMITTED; both companies recomputed on reassignment; premises untouched — routes/systems.py
- §3.3 — insert — ambiguity — decommission writes `revocation_reason` = literal `SYSTEM_DECOMMISSIONED`, no penalty invoice — routes/systems.py
- §3.3 — insert — ambiguity — renewal additionally requires a schedule `ACTIVE` at the clock (`ERR_NO_ACTIVE_FEE_SCHEDULE`) even though every rate is read from the pinned row — routes/permits.py:45
- §3.4 — insert — ambiguity — idempotency uniqueness → `ERR_INVALID_FIELD_VALUE`, evaluated after every other gate — routes/dispatch.py
- §3.4 — insert — ambiguity — `call_attempts` may be empty, stored raw, only `site_contact_id`/`outcome` read, `attempted_at` unvalidated, malformed entries skipped, unknown contact resolved before the ownership gate — routes/dispatch.py
- §3.4 — insert — ambiguity — `system_permitted_at_occurrence` snapshotted at submission — routes/dispatch.py
- §3.4 — revise — mismatch — `REJECTED`/`DECOMMISSIONED` → `ERR_INVALID_STATE`, while `SUBMITTED`/`UNPERMITTED` may lodge; flat-2 roster minimum applies to `DURESS` too — routes/dispatch.py
- §3.4 — revise — mismatch — **removed the phantom `expected_dispatch_request_version` guard**; opening an incident carries no revision guard — routes/incidents.py:28
- §3.5 — insert — ambiguity — `review_notes` discarded — routes/incidents.py:37, rt.py
- §3.5 — revise — mismatch — posture-recompute universal narrowed (exempt determination and the reinstatement application do not recompute) — routes/incidents.py:172
- §3.5 — insert — ambiguity — incident `void_reason` not retained — routes/incidents.py:40
- §3.6 — insert — ambiguity — `hearing_officer_user_id` is free text; empty string accepted — routes/dockets.py
- §3.6 — insert — ambiguity — 20-whole-day filing fallback when the premises is unpinned — routes/appeals.py:75
- §3.6 — revise — mismatch — capacity is tested **before** `ERR_HEARING_SESSION_IN_PAST` — routes/appeals.py:137
- §3.6 — insert — ambiguity — docket `cancellation_reason` unpersisted; cancelling is not the officer's own act — routes/dockets.py
- §3.6 — insert — ambiguity — `vacated_reason` = literal `APPEAL_GRANTED` — routes/appeals.py:241
- §3.6 — insert — ambiguity — the whole withdrawal operation was undocumented outside the §4 one-liner: state gate FILED/SCHEDULED, no revision guard, `X-User-ID` must equal `alarm_site_id` for **every** caller (so the role-listed administrator can never satisfy it), seat returned and `CLOSED_FOR_SCHEDULING` docket reopened, incident back to `COUNTED` — routes/appeals.py:250-277
- §3.7 — insert — ambiguity — the triggering incident need only resolve; it need not belong to the premises or be chargeable — routes/suspensions.py
- §3.7 — insert — ambiguity — the basis gate is basis-independent and an unpinned premises yields `ERR_SUSPENSION_BASIS_NO_LONGER_MET` — routes/suspensions.py `_basis_holds`
- §3.7 — insert — ambiguity — the reinstatement application writes only the order — routes/suspensions.py
- §3.7 — revise — mismatch — **handoff 2**: lift gate accepts `PAID` **or** `VOIDED`; net "not above zero" — routes/suspensions.py:194
- §3.8 — insert — ambiguity — a `VOIDED` invoice is neither referable nor adjustable (`ERR_INVALID_STATE` at position 17) — routes/invoices.py
- §3.8 — insert — ambiguity — `WRITE_OFF` off-stage → `ERR_INVALID_STATE` — routes/invoices.py
- §3.9 — insert — ambiguity — `explicit_allocations` shape rules → `ERR_INVALID_FIELD_VALUE` at position 5, after premises resolution and before invoice resolution — routes/payments.py `_read_explicit`
- §3.9 — revise — mismatch — roll-up trigger list enumerated; registration rejection and the reinstatement application excluded — routes/systems.py, suspensions.py
- §3.10 — insert — ambiguity — licence collision → `ERR_INVALID_FIELD_VALUE` — routes/companies.py:36
- §3.10 — insert — ambiguity — `period_end <= period_start` → `ERR_INVALID_FIELD_VALUE`, after resolution and ownership — routes/reports.py
- §3.10 — insert — ambiguity — `variance_notes` written on either review outcome, null when omitted — routes/reports.py
- §3.10 — insert — ambiguity — `REINSTATE` leaves the `probation_started_at` anchor untouched rather than restamping it — routes/companies.py:83
- §3.10 — insert — ambiguity — every manual status action bumps `version` by exactly 1, takes `status_reason` as required free text, and answers with the company row — routes/companies.py:64-93
- §4 preamble — insert — ambiguity — the created row is what a write returns; the two §2.6 admin capabilities are the only null-`data` responses; persisted reason fields (`refusal_reason`, `rejection_reason`, `revocation_reason`, `vacated_reason`, `status_reason`, payment `void_reason`, `variance_notes`) enumerated against the discarded ones — rt.py:34
- §4 table (5 rows) — revise — mismatch — filter enumerations corrected/completed for premises, systems, dispatch requests, invoices and reports — routes/sites.py, systems.py, dispatch.py, invoices.py, reports.py

## Prior-pass sentence refined (not reverted)
- **§3.8**, pass 2's "it is not tested at the field-validation positions but **last of all**, after every check below has passed" → "but **late**, after every check below has passed **save the one test that cannot be run without it — the amount-fits test**." `routes/invoices.py` raises the missing-`amount_cents` error before `ERR_ADJUSTMENT_EXCEEDS_OUTSTANDING`, so "last of all" was a false universal. The claim was narrowed, not removed.

## Deliberately left unpatched
- `routes/invoices.py` checks `ERR_INVOICE_UNDER_APPEAL` before `ERR_NO_ACTIVE_FEE_SCHEDULE`, inverting §2.10's positions 43 < 52 — **unreachable**: an appealed incident implies its premises is pinned, so the second condition cannot hold when the first does.
- `engine.unpermitted_cascade` issues the penalty invoice even when the system is not `PERMITTED` — **unreachable**: a system can never hold two live permits and `EXPIRED` permits are not revocable.
- `reported_cancellation_count` is maintained but feeds no metric — the PRD never claims otherwise, so no edit was warranted.
- One self-correction mid-pass: my first §2.10 roster wording ("the same flat minimum everywhere it is enforced") was a false universal, since `serve_order` freezes `min_ecv_contacts = 2 + prior`; I re-edited it before moving on.

### Step 9 — orchestrator verification (final gate)

- `wc -lc`: PRD.md 542/140,805 → PRD_FINALIZED.md 546/147,472 → PRD_COMPLETED.md 546/171,173.
  Cumulative Step 9 growth +23,701 chars across 87 edits (15 + 17 + 55).
- `cmp PRD_FINALIZED.md PRD_COMPLETED.md` → differs. A byte-identical result would have meant the
  scan never ran; the three-pass partition avoided that failure mode.
- Tail of PRD_COMPLETED.md still ends on the `ERR_ALLOCATION_MISMATCH` catalogue row — no truncation.
- Independent coverage re-check against SCAFFOLD.yaml: 75/75 endpoints and 74/74 error ids still
  present in PRD_COMPLETED.md (0 missing) — no section or table row was lost to the editing.
- `find workspace/implementation test_suite test_helpers -name '*.py' -newermt '2026-09-03 08:12'`
  → empty. Steps 8 and 9 touched documentation only, so the verified 8-round × 267/267 sweep at
  08:11 still describes the shipped implementation and test suite exactly.

PIPELINE COMPLETE. Step 9 has written workspace/PRD_COMPLETED.md.
