# Worklog — task_2725_nurse_triage_call_center_symptom_protocol_routing

## Step 1: Create task directory — 2026-09-04T12:18:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2725_nurse_triage_call_center_symptom_protocol_routing` and its `workspace/` subdirectory. Index 2725 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed (concurrent pipelines on this host would collide on auto-allocation).

## Step 2: Generate scaffold — 2026-09-04T13:50:00.000Z

All three artifacts are written, lint-clean, and verified. Nothing outside the task's own directory and the skill spec was consulted.

## Files (absolute paths)
- `SCAFFOLD.yaml` — **3185 lines** (158 KB)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — **1997 lines** (133 KB)
- `SCAFFOLD_CORNER_DESIGN.yaml` — **4180 lines** (269 KB)

Top-level key check: SCAFFOLD.yaml holds only `scenario, domain_name, api_prefix, complexity_profile, difficulty_notes, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` (neither design key present); each design file has exactly one top-level key.

## §1.0–§1.7 coverage
- **13 entities**: Practice, Nurse, NurseLicense, NurseShift, CoverageWindow, Patient, SymptomProtocol, TriageCall, ProtocolAssessment, Disposition, WarmTransfer, CallbackTask, ComplianceAuditRecord (topology flat).
- **6 state machines** over 5 entities (TriageCall, Disposition x2 parallel dimensions advice+audit, CallbackTask, WarmTransfer, CoverageWindow) — `state_machine_shape: parallel`.
- **15 calculations**, including the dual-variant pair (`assessment_acuity_score` provisional/confirmed-DOB, `practice_concordance_rate` strict/band-tolerant), the tiered `practice_after_hours_invoice`, the ranked `nurse_assignment_selector` (load ASC → seniority DESC → created_at ASC), `callback_requirement`, `staffing_adequacy`, plus two conservation invariants (`nurse_load_conservation`, `practice_ledger_conservation`).
- **52 endpoints**, **53 validation rules** (priority 1 UNAUTHENTICATED → 53 PRACTICE_COMPLIANCE_HOLD), **53 errors**, **6 roles** (PlatformAdmin, IntakeAgent, TriageNurse, ChargeNurse, ComplianceAuditor, PracticeLiaison; segregation-of-duties), 1 `concurrency_rules` entry (`disposition-create-stale-call`, `expected_call_version` → 412).

## §1.8 depth design — 9 rule_ids / 20 instances
dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2 (>=2 each).

## §1.9 breadth design — 9 sections / 74 instances (50 recipes + 24 `excluded_because` stubs)
entities 8 (7+1), state_machines 11 (6+5), calculations 14 (5+9), validations 24 (20+4), endpoints 6 (3+3), errors 2, rbac 4, cross_cutting_complexity_layers 4 (2+2), consistency_model 1.

## Verification
Self-checks passing: every stub's cited `difficulty_instance` resolves by name; no stub carries a `test_recipe`; instance names unique across the union of both design files; all 53 §1.6 errors are triggered by at least one `expect_error:`; all 53 coverage-map header names resolve to real instances; **0 unbound `${var}` placeholders**; no formula expressions left in `assert` lines; no concurrency/race vocabulary anywhere (two incidental "simultaneously" wordings were rewritten).

Final lint verdict, verbatim:

```
Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     13
  §1.8 instances scanned:     20
  §1.9 instances scanned:     50
  Calls scanned (§1.8+§1.9):  1060

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Fixes made along the way that are worth knowing: bracket-form `state_machines[...]` grounds had to become dot form; grounds pointing at non-existent Practice/ProtocolAssessment state machines were repointed to `entities.<E>.fields.status`; four capture JSONPaths referenced wrong field names (`acuity_score`, and `requires_warm_transfer` lives on TriageCall, not Disposition); and PracticeLiaison calls to priority-15-scoped endpoints needed explicit `as_user_id: "${practice_id}"` to avoid an unintended 403.

## Step 3: Copy shared files — 2026-09-04T13:51:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T14:07:00.000Z

PRD generation complete and verified.

**Output:** `workspace/PRD.md`

**Final line count:** 499
**Last section heading:** `## 5. Error Code Catalogue` — the document ends on a complete markdown table row (`| ERR_PRACTICE_COMPLIANCE_HOLD | 409 |`), a real section boundary, not mid-sentence. No truncation. Built as 1 `Write` + 5 heredoc appends + 2 small `Edit` corrections; never a single giant write.

**Document structure (domain-derived, not copied from the example PRD):**
- §1 Introduction (3 paragraphs: clinical safety, auditability, contractual accounting)
- §2 Global Specifications — 12 subsections: Role-Based Access Control; API Response Structure (verbatim); Pagination; The Logical Clock; Common Resource Properties; Nested Path Resolution; Optimistic Concurrency on Disposition Creation; Money/Minutes/Percentage Precision; Conserved Counters and Ledgers; Cascade Discipline; Licensure and Clinical Safety Gates; The Order in Which Requests Are Rejected
- §3 Business Logic & Workflows — 10 subsections (reference data → nurses/licensure/shifts/coverage → intake/identification/consent → routing → protocol assessment → disposition/escalation/override → warm transfer → callback verification → closing/billing/reopening → outcome audit and readouts)
- §4 Endpoint Definitions (exactly 4 columns)
- §5 Error Code Catalogue (exactly 2 columns)

## Hard Contract Reports

**Contract 1 — Field-Name Coverage: PASS**
```
entities[].fields:            123 required, 123 present, 0 missing
endpoint write inputs:        78 required,  78 present, 0 missing
endpoint query params:        23 required,  23 present, 0 missing
computed-read output fields:  26 required,  26 present, 0 missing
```
Also verified: all state-machine state strings present (0 missing), all entity enum values present (0 missing), §2.2 block byte-identical to `section-2.2-response-structure.md` (True).

**Contract 2 — Rule Coverage: PASS**
```
validations:        53 of 53 present, enumerated in §2.12 in strictly ascending
                    priority order (numbered items 1..53, ascending == True),
                    each with error_id, trigger condition and full applies_to scope
concurrency_rules:   1 of 1  (§2.7: POST /dispositions, expected_call_version,
                    ERR_STALE_CALL_VERSION, HTTP 412)
state_machines:      6 of 6 (TriageCall cyclic incl. the 4-hop reassessment loop;
                    Disposition advice_status and audit_status as independent
                    parallel dimensions on one row; CallbackTask branching with
                    self-loop; WarmTransfer branching; CoverageWindow with lazy expiry)
                    — every transition's from/to, preconditions and side effects prosed
calculations:       15 of 15, all with worked examples, dual variants preserved
                    (acuity intake-provisional vs nurse-confirmed; strict vs
                    band-tolerant concordance), all rounding modes and boundary
                    inclusivity stated
endpoints:          52 of 52 rows; method+path exact match to scaffold, 0 missing,
                    0 extra, 0 role mismatches against endpoints[].roles
errors:             53 of 53 rows; every error_id/http_status pair matches the
                    scaffold exactly, no duplicates, and all 53 are also named
                    in §2 or §3 prose (0 unreferenced)
```
Note: the subagent's earlier working count of "50 errors / 14 calculations" was wrong; the scaffold has 53 errors and 15 calculations, and all are covered.

**Contract 3 — §3 Path Purity: PASS**
```
§3 backtick tokens scanned: 925
tokens starting with "/":   0
bare HTTP method tokens:    0
method+path tokens:         0
unbacktick'd "METHOD /path" in §3 prose: 0
```
Paths appear only in §2.12 (where the validation scope table legitimately needs them) and §4.

**Additional checks:** no `harder than expert`, `beyond_expert`, `difficulty`, `test_recipe`, or `Generate task` wording anywhere in the file; no fuzzy words (`approximately`, `roughly`, `conservatively`, `more or less`); the hard constraint was honoured — neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

**One scaffold defect found and worked around:** the `staffing_adequacy` calculation's own worked-example text reads `required_nurse_minutes ceil(3500/80) == 35`, which is internally inconsistent (3500/80 = 43.75). The stated formula (`offered_call_count * 14 * 100 / 80`) yields 2800/80 = 35 for 2 calls, and every downstream scaffold example uses 35, so the generator treated "3500" as a typo and encoded the formula plus the value 35. Flagged for whoever owns the scaffold.

**Orchestrator verification:** independently confirmed by the orchestrator — 499 lines, final heading `## 5. Error Code Catalogue`, tail ends on a complete table row, grep for difficulty/scaffold/test_recipe leakage returns nothing.

## Step 5: Generate unit tests — 2026-09-04T15:21:00.000Z

Generation is complete. Both output directories are at the task root — `test_helpers/` and `test_suite/` — and nothing was written under `workspace/` (verified with `ls -la` on the task root and a `find`).

## Stage 1 — `test_helpers/` (2313 lines, 50 exports, import-verified)

`__init__.py` 96, `api_client.py` 289, `api_errors.py` 185, `assertions.py` 275, `constants.py` 236, `factories.py` 320, `fixtures.py` 558, `test_users.py` 100, `types.py` 254.

## Stage 2 — `test_suite/` (7097 lines, 222 tests, 25 files + `conftest.py` 12)

Queue A — 78 tests (`test_01`–`test_12`): 304, 276, 145, 192, 115, 195, 134, 210, 192, 246, 231, 93 lines.

Queue B — 144 tests (`test_13`–`test_25`): 368, 386, 562, 334, 383, 404, 553, 322, 270, 282, 155, 429, 304 lines. Files added this session: `test_22_computed_reads_and_listings.py` (282, 8 tests — the 3 `endpoints` instances), `test_23_authentication_and_error_envelope.py` (155, 6 — the 2 `errors` instances), `test_24_role_sets_and_scoping.py` (429, 14 — the 4 `rbac` instances), `test_25_concurrency_selector_and_consistency.py` (304, 9 — the 2 `cross_cutting_complexity_layers` instances plus the 1 `consistency_model` instance).

## Coverage audit (scripted against both design indices)

- 20/20 non-stub difficulty instances translated, every one with >=2 tests (none at 1, none at 0).
- 50/50 non-stub corner instances translated, every one with >=1 test. The 24 `excluded_because:` stubs were not translated.
- No `Design:` tag points at a non-existent instance; every test carries exactly one tag; no untagged or dual-tagged tests.
- **Instances skipped: none.** Two design triggers were dropped as not PRD-derivable while still translating their instance from PRD-grounded triggers: (a) `errors/missing_or_malformed_auth_headers...` asserts 401 for an *unrecognised* role string, but PRD §2.1 uniquely derives 403 there — replaced with the empty-valued header case, which §2.1 does put at 401; (b) the same instance-family's 404 leg used `GET /patients/{id}`, whose not-found behaviour the PRD never states (§2.12 item 6 guards only `match-patient`) — the 404 class is exercised through `match-patient` instead.

## Verification run

`python3 -m compileall` clean over both directories; `import test_helpers` succeeds. A docstring audit confirmed all 222 citations are whitespace-normalised verbatim PRD substrings. That audit also caught and fixed 10 pre-existing citation defects in earlier files (elided quotes with `...`, paraphrases, one wrong section label, and 2 docstrings with no quote at all) in `test_09`, `test_10`, `test_13`, `test_14`, `test_15`. No server was started, no pytest run, no `pkill`.

**Orchestrator note:** Steps 5 and 6 were launched sequentially rather than in one message, so Step 6 lost its physical isolation from `test_suite/`. Compensated by an explicit absolute prohibition in the Step 6 prompt (no read/list/glob/grep of `test_suite/` or `test_helpers/`, nor either design yaml); the Step 6 subagent confirmed compliance in its summary.

## Step 6: Generate implementation — 2026-09-04T15:55:00.000Z

Implementation complete and verified end-to-end.

## Files written (`workspace/implementation/`)

| file | lines |
|---|---|
| `start.sh` | 10 |
| `requirements.txt` | 1 |
| `app.py` | 70 |
| `util.py` | 151 |
| `errors.py` | 78 |
| `store.py` | 93 |
| `envelope.py` | 83 |
| `auth.py` | 52 |
| `validators.py` | 163 |
| `serializers.py` | 247 |
| `calc.py` | 436 |
| `cascades.py` | 210 |
| `lookups.py` | 77 |
| `routes/__init__.py` | 0 |
| `routes/practices.py` | 160 |
| `routes/coverage.py` | 79 |
| `routes/nurses.py` | 151 |
| `routes/protocols.py` | 82 |
| `routes/calls.py` | 384 |
| `routes/dispositions.py` | 275 |
| `routes/transfers.py` | 151 |
| `routes/callbacks.py` | 135 |
| `routes/clock.py` | 21 |
| **total** | **3109** |

Every file was built with a small first `Write` plus successive `cat >> ... <<'PYEOF'` appends; `__pycache__` was removed after testing so only source remains.

## Endpoints: 52 / 52
Enumerated `app.url_map` and diffed against the 52 rows of PRD §4 — exact 1:1 match on method + path, no extras (Flask's `static` excluded), `strict_slashes=False`.

## Structure
- **6 state machines** live with their resources: call lifecycle (8 states, `INTAKE→...→CLOSED` plus the `DISPOSITIONED→ASSESSING` re-assessment loop and `CLOSED→DISPOSITIONED` reopen) in `routes/calls.py`; the two parallel Disposition dimensions (`advice_status` x `audit_status`) in `routes/dispositions.py`; callback task in `routes/callbacks.py`; warm transfer in `routes/transfers.py`; coverage window (with lazy expiry) in `routes/coverage.py`; practice status/compliance posture in `routes/practices.py`. Derived statuses (licence, shift) are computed from the logical clock in `serializers.py`. All multi-hop consequences (the 4-hop supersede cascade, void chain, warm-transfer hold, conserved counters/ledgers) are centralised in `cascades.py`, so no route re-implements a cascade.
- **15 calculations** are all in `calc.py` as one named function each, in PRD order (after-hours determination, coverage, acuity score with age/pregnancy/red-flag modifiers, band, 5-step disposition recommendation, advice fee, after-hours invoice, outcome variance, concordance summary, nurse selection ordering, callback requirement, staffing adequacy), plus the two conservation invariants enforced through `cascades.py`. Money uses `Decimal` with ROUND_HALF_UP, round-per-call-then-sum; percentages half-up to 1 dp.
- **53 validations** are enforced in strict global priority order: priorities 1–2 in `auth.authorize`, 3 in `validators.py` (all schema/type/range failures → `ERR_INVALID_REQUEST`), 4–13 as the ordered `lookups.*` resolvers, 15 in `auth.practice_scope_guard`, and 14 + 16–53 as an explicitly ordered comment-numbered gate sequence at the top of each handler before any write. The one state-mutating rejection (`ERR_NO_LICENSED_NURSE_AVAILABLE` bumping `deferred_assignment_count`) is implemented in `assign_nurse`. `store.touch()` de-duplicates the version bump per request via `flask.g`, so a row touched twice in one cascade increments exactly once.

## Storage
In-memory only — 13 Python dicts on a single `Store` instance in `store.py`, plus the logical clock starting at `2026-08-01T00:00:00Z`. No SQLite, no file/JSON persistence, no `/tmp` cache. Nothing is seeded, preloaded or hardcoded: a fresh process has zero entities, which is what makes `--isolation per-test-server` sound.

## Verification performed
- In-process smoke (Flask `test_client`) reproduced every PRD worked example: acuity 55+16=71 → `ED_NOW`; HIGH_RISK task due +2 h with 3 attempts; OCC 412; segregation-of-duties 403 then `VERIFIED`; 18 min @ 4225 millicents → 20 billable / 85c; invoice `{85, 0, 0, 85}`; `ED_ADMITTED` vs `ED_NOW` → `UNDERTRIAGE` gap 7 → `VARIANCE_ESCALATED`; duplicate audit 409; reopen restoring ledgers to 0/0.
- Real server boot: `PORT=39417 bash start.sh` came up clean and a live HTTP script covered the paths the in-process run missed — `ERR_NO_ACTIVE_COVERAGE`, the 30-min two-sided coverage buffer (20 min → 409, 40 min → 201), activate + lazy `EXPIRED`, minor-consent gate, after-hours intake, infant score 89 → `EMERGENCY_911` with `OFF_ROTATION` hold, the full warm-transfer chain incl. state mismatch / already-open / low-confidence rejections, `ERR_EMERGENCY_DEESCALATION_FORBIDDEN`, the 4-hop re-assessment cascade (assessment `SUPERSEDED` → disposition `VOIDED` → task `CANCELLED` → `open_callback_count` 0 → high-risk hold released), `WORSENED` → `ESCALATED` + `VARIANCE_ESCALATED`, staffing adequacy, and abandon releasing all holds. The server was then killed by its exact port-owning PID (2526429) — no `pkill`/`killall` was ever run.
- One PRD detail flagged as deliberate: the concordance input set uses the half-open `[audit_period_start_utc, clock)` window exactly as PRD line 370 states ("at or after ... and strictly before the logical clock"), so an audit record filed at the current clock instant only enters the summary once time advances.

The subagent confirms it never read, listed, globbed or grepped `test_suite/` or `test_helpers/`, and never opened `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`. The implementation derives solely from `PRD.md`, `SCAFFOLD.yaml` and `INSTRUCTION.md`.

## Step 7: Run tests and iterate — 2026-09-04T16:15:00.000Z

Clean sweep achieved.

## Summary

**Iterations run:** 2

**Iteration 1** — all 8 rounds identical: 227/231 passed, 4 failures, perfectly reproducible (no flakiness, no load-induced timeouts). Union of failures:
- `test_02::test_the_audit_dimension_closes_quietly_against_the_final_level` — setup 409 `ERR_CALLBACK_INVALID_STATE`
- `test_02::test_a_concordant_close_leaves_every_practice_variance_counter_at_zero` — same setup 409
- `test_19::test_the_undertriage_record_puts_the_practice_under_review` — `assert 0 == 1`
- `test_24::test_the_platform_admin_reads_both_practices` — `KeyError: 'practice_id'`

**Tests deleted:** none (no test failed STEP 1a/1b wholesale).

**Assertion removed under STEP 1c partial-coverage split (1):**
- `test_suite/test_24_role_sets_and_scoping.py:258` — `assert seen_by_admin["practice_id"] == practice_2["id"]`. PRD §3.10 line 370 and §4 line 394 enumerate the compliance-summary response fields (`audited_count`, both concordance counts and rates, `undertriage_count`, `overtriage_count`, `variance_severity_points_total`, `open_variance_count`, `compliance_posture`) and never state the readout echoes `practice_id` — RESPONSE-FIELD SILENCE, a faithful reader would omit it. Replaced with the PRD-covered `compliance_posture == "NORMAL"`, which preserves the test's actual point (the `PlatformAdmin` read of a foreign practice succeeds).

**Fixes applied to `test_helpers/` (1):**
- `test_helpers/fixtures.py` — added `live_callback_for()` and switched `reach_and_verify()` to use it instead of `callback_for()`. `callback_for()` returns `rows[0]`, the oldest task; after a de-escalating override PRD §3.6 leaves that row `CANCELLED` and creates a `PENDING` replacement, so `reach_and_verify` was attempting a terminal task and the PRD-faithful server correctly answered `ERR_CALLBACK_INVALID_STATE`. `callback_for()` was left untouched because `test_06` deliberately asserts the cancelled row.

**Fixes applied to `test_suite/` (1, faithfulness correction):**
- `test_suite/test_19_parent_state_and_eligibility_gates.py` — added `world.set_clock("2026-08-03T21:00:00Z")` between filing the audit record and reading the compliance summary. PRD line 370 defines the readout's input set as records created "at or after the practice's `audit_period_start_utc` and **strictly before the logical clock**"; the test read the summary at the same clock instant it filed, so `undertriage_count` was correctly 0. (Its sibling assertions on the *live* counters `open_variance_count`/`compliance_posture` already passed, confirming the cascade itself was right.)

**Fixes applied to `implementation/`:** none — no implementation defect was found. All 4 failures were test-artifact bugs or PRD-silent assertions.

**Final sweep (iteration 2):** all 8 rounds `passed == total == 231`, `failed == 0`, `errors == 0`. All eight `results.1.json` … `results.8.json` are present on disk in `workspace/implementation/`.

`worklog.md` was not touched by the subagent. `__pycache__` directories were cleaned so `implementation/` and the test dirs contain source only.

**Orchestrator verification (independent):** re-read all 8 `results.$i.json` directly — every round reports `passed=231 total=231 failed=0 errors=0`, files timestamped 16:15, ~80 KB each. Sweep artifacts confirmed real, not merely claimed.

**Step 8 decision:** NOT skipped. The skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes; here there was 1 `test_helpers/` fix, 1 `test_suite/` fix and 1 assertion removal, so Step 8 runs. Because there were 0 `implementation/` fixes, a byte-identical `PRD_FINALIZED.md` is a legitimate possible outcome — the only genuine PRD silence surfaced is the compliance-summary response-field list.

## Step 8: Finalize PRD — 2026-09-04T16:22:00.000Z

Done. One edit; everything else in `<step_7_diff>` traced to test-artifact bugs already determined by PRD prose.

## Line counts
- `PRD.md`: 499 lines; `PRD_FINALIZED.md`: 499 lines. Line-count delta 0 (0.000%). One line revised in place (1/499 lines touched = 0.2% of lines).

## Changes
- **§3.10 (compliance/concordance readout), line 372** — *revise* — appended a closing clause pinning the compliance-summary `data` object to exactly the ten already-enumerated fields, stating explicitly that it echoes nothing of its request back (no `practice_id`) and, being a computed figure rather than a stored row, carries no `id`/`created_at`/`updated_at`/`version` — `implementation/calc.py:316-326` (the returned dict) and `implementation/routes/practices.py:132-137` (`object_response(practice_concordance_summary(row))`, no wrapping/augmentation).

## Per-edit pre-edit search log

**Edit 1 — subject: the field set of the `GET /practices/{id}/compliance-summary` response `data` object.**

(b) Paths enumerated, read or grepped:
- `grep -rn "practice_concordance_summary\|concordance_input_set"` → only producer `implementation/calc.py:291` and only callsite `implementation/routes/practices.py:137`. No second endpoint, no list variant, no serializer wrapper.
- `implementation/calc.py:291-326` — read in full; returns exactly 10 keys, all 10 already named in PRD §3.10 (5 in the concordance paragraph, 5 in the raw-material paragraph). No `practice_id`, no `id`, no timestamps.
- `implementation/calc.py:268-289` (`concordance_input_set`) — confirms the input-set predicate matches PRD line 370 verbatim in effect (`created_at < clock`, `>= audit_period_start_utc`, live advice, call belongs to practice), so no edit was needed for the test_19 clock item.
- `implementation/routes/practices.py:132-138` — route adds nothing; `practice_scope_guard` then `object_response`.
- `implementation/envelope.py` (`object_response`, `base_meta`) — the only additions are envelope `meta.api_request_id`/`api_request_timestamp`, which live outside `data`; this is why the wording says "`data` object" rather than "payload/response".
- Parallel computed readouts, to avoid over- or under-generalising: `implementation/calc.py:218-239` (`practice_after_hours_invoice` — also echoes no `practice_id`, but deliberately left unclaimed since it is out of Step 7 scope) and `implementation/calc.py:391-436` + `implementation/routes/nurses.py:144-151` (`staffing-adequacy` — the route *does* prepend `state_code`, `window_start_utc`, `window_end_utc`, matching PRD's existing echo sentence).
- `implementation/serializers.py:17-36` (`practice_json`) — the sibling `GET /practices/{id}` read *does* carry `id`, `created_at`, `updated_at`, `version` and `compliance_posture`; the new sentence therefore had to be scoped to "this readout" and must not read as a claim about practice reads generally.

(c) Wording adjustments made for consistency: scoped the claim to "this readout's `data` object" (not "response"/"payload") so envelope `meta` fields are not contradicted; scoped the no-`id`/no-timestamp clause to "this readout" with the rationale "a computed figure rather than a stored row" so it cannot be read back onto `practice_json` or any other stored-resource serializer; kept the "unlike the staffing readout" contrast because `routes/nurses.py:146-149` really does echo, preserving the PRD's existing echo sentence rather than colliding with it; deliberately made no claim about the after-hours-invoice readout's field set (out of Step 7 scope, and a claim there would be a new unforced universal).

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (372), md5s differ (`491d4798…` vs `82d0ae69…`). The edit is real, not a no-op copy.

**Step 9 plan:** per the known failure mode where a single-pass Step 9 silently no-ops (leaving `PRD_COMPLETED.md` byte-identical to its source), Step 9 will run as THREE sequential module-partitioned passes over one shared `PRD_COMPLETED.md`: pass 1 = infrastructure/auth/validation/serialization layer (`app.py`, `util.py`, `errors.py`, `store.py`, `envelope.py`, `auth.py`, `validators.py`, `lookups.py`, `serializers.py`) and performs the initial `cp`; pass 2 = `calc.py` + `cascades.py`; pass 3 = all nine `routes/*.py`. Passes 2 and 3 must NOT re-copy the file.

## Step 9: Complete PRD — 2026-09-04T17:05:00.000Z

Run as THREE sequential module-partitioned passes over one shared `PRD_COMPLETED.md`. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edited in place with the Edit tool only.

### Pass 1 of 3 — infra/auth/validation/serialization (`app.py`, `util.py`, `errors.py`, `store.py`, `envelope.py`, `auth.py`, `validators.py`, `lookups.py`, `serializers.py`)

`cp PRD_FINALIZED.md PRD_COMPLETED.md` performed first (source verified present, 499 lines / 108,928 chars). After edits: 499 lines / 114,504 chars (char delta +5,576; every change an in-paragraph insert/revise).

Counts: **16 ambiguity-pins, 4 mismatch-revisions** across 19 Edit calls / 20 subjects.

- §2.1 — insert — ambiguity — whitespace-only header counts as empty for `ERR_UNAUTHENTICATED`; unrecognised role string draws `ERR_UNAUTHORIZED` — auth.py:26-33
- §2.2 success bullets — insert — ambiguity — `api_request_id` is `req_` + 20 uppercase-alphanumeric chars; `api_request_timestamp` comes from the logical clock — envelope.py:19-27
- §2.2 success bullets — insert — ambiguity — pagination `meta` keys on list endpoints only; object `meta` has exactly two keys — envelope.py:30-31,70-77
- §2.2 error format — revise — mismatch — "4xx" → "4xx, and any 5xx the server produces" — app.py:55-57
- §2.2 error meta bullet — insert — ambiguity — unknown path → `ERR_INVALID_REQUEST` 404; wrong method → `ERR_INVALID_REQUEST` 405 — app.py:43-53
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` is 400, empty string takes the default, no `offset` ceiling, over-large offset yields empty successful page — envelope.py:47-72
- §2.3 — insert — ambiguity — equal `created_at` ties break by creation order within the process — store.py:91-93
- §2.5 — insert — ambiguity — sub-millisecond precision truncated, not rounded, on render — util.py:48-56
- §2.5 — insert — ambiguity — fixed key set: "absent" fields present as JSON `null`, never omitted (sole omissions `updated_at`/`version` on the three immutable resources); `dob`/`expires_on` as `YYYY-MM-DD` — serializers.py:9-14
- §2.5 — insert — ambiguity — `updated_at` equals `created_at` at creation; `version` rises exactly one **per request** even when several paths write the same row — store.py:43-73
- §2.6 — insert — ambiguity — left-to-right applies to path segments only; query-param schema checks (priority 3) still precede the outer lookup — envelope.py:63
- §2.12 item 3 — insert — ambiguity — JSON `null` = absent; wrong JSON type malformed (incl. bool-as-int, float-as-int); length-bounded strings reject `""` (exception `location_address_line`); accepted timestamp forms; absent body = `{}`, non-object/unparseable = 400; enum-valued list filters reject out-of-set values while free-form filters match nothing — validators.py:18-144
- §2.12 item 15 — revise — mismatch — on coverage-window activate the scope guard compares `X-User-ID` to the *window's* practice — auth.py:49-52 + coverage.py:62
- §2.12 item 26 — revise — mismatch — gate fires only when `recording_reference` is absent; `""` already rejected at priority 3 — validators.py:52
- §3.3 — revise — mismatch — same correction in the consent narrative — validators.py:52
- §3.1 — insert — ambiguity — office hours zero-padded `HH:MM`, `00:00`–`23:59` — util.py:38
- §3.5 — insert — ambiguity — assessment echoes both raw inputs as supplied, including the mode-irrelevant one, `null` when omitted — serializers.py:154-171
- §3.7 — insert — ambiguity — `location_lat`/`location_lng` returned as decimal numbers even for integral input — validators.py:83-91
- §3.9 — insert — ambiguity — `reopen_reason` validated but not persisted, absent from the call representation — serializers.py:121-151
- §4 intro — insert — ambiguity — trailing slash tolerated on every path — app.py:30

Already fully pinned, no edits needed: `errors.py` (all 53 ids/statuses verified byte-for-byte against §5 by script, order included) and `lookups.py` (each resolver raises exactly the not-found id §2.12 items 4-13 assign it).

### Pass 2 of 3 — calculation/cascade layer (`calc.py`, `cascades.py`)

114,504 → **118,621 chars**, 499 lines throughout. Pass 1's work preserved (30 lines differ from `PRD_FINALIZED.md` = pass 1's 20 + pass 2's 10, two landing in one paragraph). Counts: **10 ambiguity-pins, 1 mismatch-revision**.

- §2.9 — insert — ambiguity — conserved counters/ledgers floor at zero — cascades.py:32,39,50,63
- §2.10 — revise — mismatch — variance chain's posture flip and window blocking gated on `open_variance_count` reaching `variance_review_threshold`, not unconditional — cascades.py:134
- §3.2 — insert — ambiguity — lazy `ACTIVE→EXPIRED` sweep also runs on an activation attempt (a fourth trigger) and is scoped to the one practice — calc.py:61-70, coverage.py:63
- §3.3 — insert — ambiguity — abandonment does not touch the call's protocol assessments — cascades.py:198-203
- §3.4 — insert — ambiguity — tie surviving load/seniority/`created_at` breaks by registration order within the process — calc.py:350
- §3.6 — revise — ambiguity — override `due_by_utc` measured from the current logical clock, not the disposition's `created_at`; all four branch outcomes made exhaustive — cascades.py:71-114, calc.py:362-385
- §3.6 — insert — ambiguity — warm-transfer hold re-derived in *both* directions; escalation to `EMERGENCY_911` sets the flag, `+1` on `pending_high_risk_count`, `OFF_ROTATION` at cap; nurse adjusted is always `determined_by_nurse_id` — cascades.py:25-35
- §3.8 — revise — ambiguity — hops 3/4 conditional on threshold; once met hop 4 re-runs on every later variance; posture never returns to `NORMAL` — cascades.py:131-138
- §3.10 — insert — ambiguity — a practice with no `audit_period_start_utc` gets no lower bound — calc.py:277
- §3.10 — insert — ambiguity — invoice readout's seven fields are the whole `data` object — calc.py:231-239
- §3.10 — revise — ambiguity — staffing overlap contributes whole minutes with part-minutes discarded, shift `status` never filters, `licensed_nurse_count` read off licences alone — calc.py:402-415

Already fully pinned: `after_hours_determination`, `has_active_coverage`, `license_status`, `shift_status`, `nurse_has_active_license`, `nurse_on_running_shift`, all acuity modifier functions and `assessment_acuity_score`, `band_acuity`, `disposition_recommendation`, `call_advice_fee`, `outcome_variance_classification`, `practice_concordance_summary`, the invoice tier table, `callback_requirement`, `staffing_adequacy`'s demand formula/posture boundaries, and in cascades `reevaluate_eligibility`, the ledger pair, `open_callback`/`close_callback`, `create_callback_task`, `cancel_open_tasks`, `block_draft_coverage_windows`, `clear_warm_transfer_hold`, `void_disposition`, `supersede_active_assessments`. Noted `active_assessment_of` (cascades.py:206) is dead code with no callsite and no PRD subject.

### Pass 3 of 3 — route layer (all nine `routes/*.py`)

118,621 → **123,217 chars** (+4,596), 499 lines. Passes 1 and 2 verified intact by spot-checking markers from both. Counts: **16 ambiguity-pins, 5 mismatch-revisions** across 21 edits.

- §3.2 — revise — ambiguity — `max_concurrent_calls` defaults 8, `high_risk_cap` defaults 1 (so a default nurse goes `OFF_ROTATION` on a single pending warm transfer) — nurses.py:20-21,37-40
- §3.2 — revise — **mismatch** — `license_number` uniqueness is NOT enforced; duplicates and multiple licences per nurse+state accepted — nurses.py:55-73
- §3.2 — insert — ambiguity — `expires_on` never compared to the clock at filing, so a licence may be created already `EXPIRED` — nurses.py:61
- §3.1 — revise — **mismatch** — patient `mrn` uniqueness within a practice is NOT enforced — practices.py:89-105
- §3.1 — revise — **mismatch** — protocol `code` global uniqueness is NOT enforced — protocols.py:24,52
- §3.1 — insert — ambiguity — `min_disposition_level` optional, defaults `HOME_CARE` — protocols.py:34,47
- §3.1 — insert — ambiguity — retire takes no body and has no state gate; re-retiring succeeds and bumps `version` — protocols.py:76-82
- §3.1 — revise — ambiguity — supplying the status a practice already holds is accepted and still bumps `version` — practices.py:69-77
- §3.2 — insert — ambiguity — the draft path runs no lazy-expiry sweep, so a stale `ACTIVE` window still blocks — coverage.py:37-43
- §3.10 — insert — ambiguity — malformed `state_code`, unparseable bound, inverted window, empty-string params all `ERR_INVALID_REQUEST` — nurses.py:134-143
- §2.12 item 3 — insert — ambiguity — same staffing clauses, plus `retire`/`activate`/`complete-handoff` read no body so item 3 cannot fire — protocols.py:78, coverage.py:60, transfers.py:138
- §2.12 item 17 — revise — **mismatch** — warm-transfer creation imposes no call-status from-set (gates on `requires_warm_transfer`); override added to the guarded list — transfers.py:30-53, dispositions.py:166
- §2.12 opening + closing — revise/insert — **mismatch** — the one departure from ascending priority: on the override path check 19 fires before check 17 — dispositions.py:161,166
- §2.7 — insert — ambiguity — `expected_call_version` range-checked at minimum 0; negative is `ERR_INVALID_REQUEST`, 0 well formed but never matches — dispositions.py:58
- §3.6 — insert — ambiguity — `override_reason_code`/`override_narrative` persisted only when `final_level != recommended_level` — dispositions.py:96-97
- §3.3 — insert — ambiguity — `match_confidence_pct` copied verbatim, optional on every method, retained on an `MRN` match — calls.py:139-152
- §3.5 — insert — ambiguity — the mode-irrelevant input is ignored for scoring only; still schema/range-checked — calls.py:230-233
- §3.7 + §2.12 item 45 — revise x2 — ambiguity — whitespace-only `location_address_line` counts as empty for `ERR_INVALID_LOCATION` — transfers.py:45
- §3.8 — revise — ambiguity — `due_before_utc` is strictly before; a task due at exactly that instant is excluded — callbacks.py:57
- §3.3 — insert — ambiguity — `abandon_reason` mandatory (1–500 chars) and persisted, unlike optional `reopen_reason` — calls.py:368,381

All nine files walked end to end, all 52 endpoints enumerated. Endpoints found already fully pinned are listed per file in the pass-3 report (practices 7, coverage 2, nurses 4, protocols 2, calls 9, dispositions 4, transfers 4, callbacks 3, clock 1).

Verdicts on the handoff notes passes 1/2 raised: nurses defaults 8/1 **pinned**; `min_disposition_level` default **pinned** while `infant_modifier_points` default 20 was **already pinned** by §3.1; staffing-readout rejections **pinned**; `expected_call_version` minimum 0 **pinned**; item-34-after-27/28 **NOT REPRODUCED** — 27 < 28 < 34, so evaluating the mismatch check last is exactly what ascending priority requires; both earlier passes misread it, and the real ordering defect on that endpoint's sibling (19 before 17 on override) was pinned instead; `VOIDED`-before-carve-out **already pinned** by item 19's own wording; `mrn` and `license_number` uniqueness **both genuinely unenforced, corrected as mismatches**, plus a third instance the handoff missed (protocol `code`); `due_before_utc` strict `<` **pinned**.

One deliberate non-edit: the `audit_status == "AWAITING_OUTCOME"` guards at callbacks.py:89,130 are unreachable-as-false, so no prose was added for a branch impl cannot exhibit.

### Orchestrator verification of Step 9

`PRD.md` 499 lines / 108,367 chars → `PRD_FINALIZED.md` 499 / 108,928 → `PRD_COMPLETED.md` 499 / 123,217. md5s all distinct (`PRD_FINALIZED` `82d0ae69…`, `PRD_COMPLETED` `29af9946…`), so the scan genuinely ran — `PRD_COMPLETED.md` is NOT a byte-identical copy. 46 lines differ between `PRD_FINALIZED.md` and `PRD_COMPLETED.md`; total char delta over the finalized PRD is +14,289. `grep '^#'` on both files is identical, confirming no section was added or removed. Single `worklog.md` at the task root, no strays under `workspace/`; `test_helpers/` and `test_suite/` at the task root; the eight passing `results.$i.json` from the final Step 7 sweep remain in `workspace/implementation/`.

**PIPELINE COMPLETE** — Step 9 has written `workspace/PRD_COMPLETED.md`.
