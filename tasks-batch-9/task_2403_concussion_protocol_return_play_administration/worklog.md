# Worklog — task_2403_concussion_protocol_return_play_administration

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `tasks/task_2403_concussion_protocol_return_play_administration/` and `tasks/task_2403_concussion_protocol_return_play_administration/workspace/` (pre-allocated task name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T09:13:21.369Z

All three artifacts are complete and pass the lint plus a full self-audit.

### Files
- `SCAFFOLD.yaml` (2110 lines, §1.0–§1.7 only)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1363 lines, single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (4045 lines, single key `scaffold_corner_design`)

### SCAFFOLD.yaml counts
11 entities, 12 state machines / 60 transitions, 12 calculations, 59 validation rows across 46 priority levels, 52 endpoints, 57 errors, 6 roles, 36 constants, 2 OCC concurrency rules. `domain_name: concussion-protocol-rtp`, `api_prefix: /concussion-program`, flat topology, cyclic + parallel state shapes, layers `[cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, optimistic_concurrency]`, `role_model: segregation_of_duties`, `consistency_model: immediate`.

### Design instances
- §1.8: 18 instances — all nine mandated rule_ids × 2.
- §1.9: 99 instances across all nine guide sections (entities 13, state_machines 23, calculations 12, validations 17, endpoints 9, errors 7, rbac 9, cross-cutting layers 8, consistency model 1); 81 full recipes + 18 `excluded_because` stubs, each citing a difficulty instance that exists by name.

### Audit results (all clean)
- `scaffold_lint.py`: **VERDICT: clean lint** — 2069 calls scanned across §1.8+§1.9, all conform to §1.5, all §1.1 FKs reverse-reachable.
- 115 instance names unique across the union of both design files; every real instance has the full seven-point shape.
- All grounds resolve into §1.1–§1.6 (entity/calc/error/constant/role/concurrency ids, `priority_N[_ERR_X]` pairs present in the ladder, endpoint keys present in §1.5, and every `Entity.FROM_to_TO` an actually-declared transition).
- Every `${var}` is bound by an earlier `captures:` in its own chain (0 unbound sites); OCC fields are always `${var}` or `${case_v} - 1`.
- Coverage: all 57 error ids are triggered by an assert (not merely cited in grounds); all 52 endpoints are actually called; every declared state in all 12 machines is exercised.
- No forbidden concurrency vocabulary in any of the three files.

### Fixes made during the audit
- Added two missing ProtocolAudit transitions (`FINDINGS_ISSUED → CLOSED_DISMISSED`, `CLUB_RESPONDED → CLOSED_UPHELD`) that validation priority 10 already permitted but §1.2 omitted.
- Corrected mislabeled state names in design grounds/asserts (`SCREENING` → `SCREENED`, `CLEARED_TO_RETURN` → `CLEARED_ON_FIELD`, `NO_CONCUSSION` → `NO_CONCUSSION_CLEARED`) and three constant names (`SEVERITY_HIGH_THRESHOLD`, `REPORT_WINDOW_OPEN_HOURS_BEFORE_KICKOFF`, `REPORT_WINDOW_LATE_MINUTES_BEFORE_KICKOFF`).
- Added instances to close coverage gaps found by the audit: `standard_crud` round-trip, sweeps of all remaining list/by-id reads, and the two previously-unexercised terminal states (`ReturnStep.FAILED_SYMPTOM_RECURRENCE`, `IncClearance.DENIED_INSUFFICIENT_DOCUMENTATION`).

## Step 3: Copy shared files — 2026-09-02T09:13:21.369Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T09:30:10.966Z

PRD generated at `workspace/PRD.md`.

**529 lines.** Title: `# Concussion Protocol & Return-to-Play Administration API — Product Requirements Document`. Ends at the §5 table with no audit footer.

**Sections:**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications & System-Wide Principles — 2.1 RBAC, 2.2 API Response Structure (verbatim), 2.3 Pagination, then 9 domain subsections: 2.4 Resource Identity/Timestamps/Logical Clock, 2.5 The Refusal Ladder, 2.6 Optimistic Concurrency, 2.7 Clinician Credentialing, 2.8 Club Compliance Posture/Escalation/Penalty Ledger, 2.9 Roster Exemption Slot Conservation, 2.10 Numeric Precision & Rounding, 2.11 Boundary Conventions for Timed Windows, 2.12 Collection Reads & Filter Parameters
- §3 Business Logic & Workflows — 11 subsections following the protocol timeline: reference data/credentialing -> baseline testing -> sideline removal & screening -> locker-room exam -> diagnosis & severity -> graduated return -> consultant clearance & return to contact -> monitoring & exemptions -> injury reporting & designations -> auditing/pricing/sanctions -> operational sweep
- §4 Endpoint Definitions — 4-column table, 52 rows, preceded by the 201-vs-200 paragraph
- §5 Error Code Catalogue — 2-column table, 57 rows

**Hard Contract audits (all machine-verified against SCAFFOLD.yaml):** Field coverage PASS (111/111 entity fields, 42/42 request bodies, 31/31 query params, 1/1 path params, 21/21 computed output fields). Rule coverage PASS (46/46 priority rungs, 2/2 OCC rejections, 60/60 transitions across 12 machines with all 46 state tokens verbatim, 12/12 calculations, 57/57 error_ids matchable with §5 statuses exact, 52/52 endpoint method/path/role triples, 93/93 enum/constraint tokens, all 36 constants' values, 10/10 sibling-branch symmetry groups). Path purity PASS (853 backtick tokens scanned in §3; 0 containing `/`, 0 bare HTTP methods). §2.2 diffed byte-for-byte against the skill's canonical file — exact match.

**Notes:** Two stray XML tags landed at the end of the first write and were removed. The withheld design files were never opened, grepped, or referenced; no sibling task directory was read. Difficulty-preserving choices flagged: pinned orders (7-step club posture propagation, 5-step findings issuance, 5-step sweep) stated as normative sequences; two-stage half-up fine rounding called out as normative with the wrong alternative named; closed 30-minute consultant exam block contrasted against the half-open rest buffer in §2.11; intentional priority-10 deferrals (`STAGE_FROZEN` -> rung 11, `MANDATORY_REMOVAL` + clearance request -> rung 34) documented at the rung where they are skipped.

## Step 5: Generate unit tests — 2026-09-02T10:09:57.566266039Z

All work is complete. Final verification: 117 tests collect cleanly, every audit green.

### Files written
**`test_helpers/`** (infrastructure, 9 modules): `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`
**`test_suite/`**: `conftest.py` + 15 test modules — 8,560 lines total.

### Test counts
| Queue | Instances | Tests |
|---|---|---|
| A (Difficulty §1.8) | 18 non-stub, 0 stubs | **36** (exactly 2 per instance, 9 files x 4) |
| B (Corner §1.9) | 81 non-stub, 18 stubs | **81** (1 per instance, 6 files) |
| | | **117 total** |

Queue A files: `test_difficulty_{dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant}.py`
Queue B files: `test_corner_{entities (14), state_machines (19), calculations (9), validations (15), endpoints_errors (10), rbac_and_layers (14)}.py`

### Coverage audit (scripted, all green)
- Every test has **exactly one** `Design:` line; 0 untagged, 0 dual-tagged, 0 tags resolving to a non-existent or `excluded_because` instance.
- All 18 queue-A instances have >=2 tests; all 81 non-stub queue-B instances have >=1; the 18 stubs have 0.
- All 130+ docstring PRD quotations machine-verified as whitespace-normalised substrings of `workspace/PRD.md` — 0 misses. (One fabricated quote was caught earlier this run and replaced with the genuine §3.10 sentence.)
- No `pytest.mark.skip/skipif/xfail`, no `pytest.mark` at all, no occurrence of the forbidden word, no design-document section references. `py_compile` clean; every test signature is `(api)`; all `fx.*`/`f.*`/`api.*`/helper imports statically resolve.

### Instances skipped
**None beyond the 18 `excluded_because` stubs.** Every non-stub instance passed the PRD-first filter.

### Design-vs-PRD divergences (PRD won in every case)
- **HTTP statuses:** the design writes 422 for ~12 error ids that §5/§2.5 pin at **409** (`ERR_GAME_NOT_IN_PROGRESS`, `ERR_STEP_ALREADY_IN_PROGRESS`, `ERR_STAGE_DWELL_NOT_MET`, `ERR_RETURN_BEFORE_EARLIEST_DATE`, `ERR_INC_CLEARANCE_MISSING`/`_EXPIRED`, `ERR_REPORT_WINDOW_*`, `ERR_NO_EXEMPTION_SLOTS`, `ERR_EXEMPTION_ALREADY_GRANTED`). Tests assert 409.
- **Field names:** design `symptom_score_at_evaluation` -> PRD `evaluation_symptom_score`; design `returned_to_contact_at` -> PRD `cleared_for_contact_at`.
- **Contradicted values dropped:** design asserts `public_injury_designation == NONE` after return to contact, but §3.9 derives `QUESTIONABLE` inside the 72-hour window — assertion omitted. Design asserts `PROTOCOL_RESTRICTED` on the player after initiation/screen/`INCONCLUSIVE`, but §3.5/§3.3 leave the player `AVAILABLE` there. Design asserts `last_symptomatic_at == null` on a case whose diagnosis symptom score was 9, but §3.5 stamps it.
- **Unreachable triggers rewritten:** design's `stage_index: 6` would be refused at rung 3, so the `CLEARED_FOR_CONTACT` state check uses a schema-valid `stage_index: 1`; the double-amendment case was rebuilt on a second entry so `ERR_REPORT_WINDOW_CLOSED` (not `ERR_RESOURCE_STATE_INVALID`) is genuinely the winner.
- **One judgement call flagged:** `Corner/rbac/club_physician_cannot_claim_observer_trigger_source` — the PRD forbids the claim ("no other role can invoke it") but names no error code, so that single assertion uses `validate_error_is_one_of([ERR_UNAUTHORIZED, ERR_INVALID_REQUEST])` while still asserting the full uniquely-derived consequence (no evaluation row, and the physician's own trigger source accepted with the 45-minute deadline).
- Two figures deliberately left unasserted as not uniquely derivable: the sweep summary's `swept_at` millisecond rendering, and `exposure_days` (0 vs null) on a freshly opened audit.

`workspace/implementation/` and all sibling task directories were never read.

## Step 6: Generate implementation — 2026-09-02T10:09:57.566266039Z

Self-audit is clean. Final state:

### Files written
`workspace/implementation/`

| File | Role |
|---|---|
| `start.sh` (executable) | guarded dep probe + `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | `flask>=3.0` |
| `app.py` | `create_app()`, blueprint registration, `ApiError`/`HTTPException`/catch-all handlers |
| `constants.py` | `/concussion-program` prefix, roles, all enums, every numeric constant, violation canonical order/weights/base cents |
| `errors.py` | all 57 error IDs with exact HTTP statuses + default messages |
| `db.py` | in-memory `Store` (11 empty dicts), logical clock defaulting to `2026-08-01T00:00:00Z`, id/timestamp/version helpers |
| `response.py` | `meta`/`response_type`/`data` envelope, `req_` ids, 3-digit-fraction UTC stamps, offset pagination |
| `validation.py` | field coercers, filter parsers, auth ladder rungs 1/2/6/7/8/9/23, entity resolvers |
| `serializers.py` | 12 output shapes incl. the 11-member computed compliance summary |
| `services/calc.py` | severity index, dual return timelines, ladder timing, `Fraction`-exact two-stage fine rounding, compliance/tier/posture bands, ledgers |
| `services/posture.py` | pinned 7-step `club_posture_propagation` with conditional version bumps |
| `services/audits.py` | manual + auto-issued audit construction |
| `services/sweep.py` | pinned 5-step sweep, 9-key summary |
| `routes/reference.py` (15), `routes/baselines.py` (4), `routes/evaluations.py` (8), `routes/cases.py` (13), `routes/audits.py` (6), `routes/reports.py` (4), `routes/ops.py` (2) | endpoint handlers |

### Endpoint count
**52** routes registered, matching the SCAFFOLD `path:` list one-for-one (51 under `/concussion-program`, plus `POST /_clock/set_current_utc` at root — LeagueAdmin-gated, as SCAFFOLD line 1955 requires).

### Self-audit results
A ~490-line end-to-end probe (kept in `/tmp/t2403_smoke.py`, not part of the deliverable) exercises the full lifecycle — reference data, baselines, sideline evaluation -> screen -> locker-room exam -> diagnosis, the 5-stage RTP ladder with rest buffers and dwell windows, INC clearance request/decide/expiry, return to contact, roster exemptions, audit findings/respond/close, sanction-freeze and dismissal-restore, symptom recurrence, injury reporting with late-filing auto-audit, two sweeps, off-season monitoring, and the auth/pagination surface. Result: **FAILURES: 0**.

The last five mismatches were all harness-expectation bugs, each confirmed against the PRD rather than patched in the implementation:
- tier band for score 72 is `TIER_2` (PRD §2.8: 60–74 inclusive), not `TIER_1`
- `assessed_fine_cents` must apply the **stamped** tier multiplier — 46000000 gross x 1.50 = **69000000**
- dismissing the second audit restores club_b to `PROBATION`/80, not `ACTIVE`/100, because the first upheld audit still counts
- `heightened_review_required` stays true at `PROBATION` (PRD line 396); only a return to >=90 clears it
- the late-filing auto-audit is 1500000 x 1.50 = **2250000** at the club's stamped `TIER_1`

Also verified: fine arithmetic matches the three SCAFFOLD worked examples (66535715 / 33267857 / 5000000) and the severity examples (82 / 94 / 100).

### Boot and storage invariants
- Cold boot from a clean tree verified; ready in ~1.6–3.1 s even with host load average ~245. Shaved ~5 s off the original by replacing the `import flask` probe in `start.sh` with an `importlib.util.find_spec` check and allowing bytecode caching.
- Fresh-process assertion: all 11 store dicts empty, clock at `2026-08-01T00:00:00.000Z`, `GET /players` returns `total_count: 0`. Nothing is seeded, preloaded or hardcoded.
- No `sqlite3`, file `open()`, `json.dump`, `pickle` or `shelve` anywhere in the tree — grep-verified. Storage is process memory only.
- `test_helpers/` and `test_suite/` were not read; no sibling task directory was touched. Stray test servers on ports 10739–10753 were shut down and `__pycache__` directories removed.

## Step 7: Run tests and iterate — 2026-09-02T13:14:00.000Z

Clean sweep achieved on the first iteration — no fixes were needed.

## Summary

**Iterations run:** 1 (one full 8-round parallel stability sweep, `--isolation per-test-server`).

**Result:** all 8 rounds report `passed == total == 117`, `failed == 0`, `errors == 0`.
Results files: `/home/ubuntu/github/CodingPRD/tasks/task_2403_concussion_protocol_return_play_administration/workspace/implementation/results.{1..8}.json`
Round logs: `/home/ubuntu/github/CodingPRD/tasks/task_2403_concussion_protocol_return_play_administration/workspace/round.{1..8}.log`

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

**Key finding — the reported "117 tests all ERRORed at setup" was an artifact, not a real defect.** Pre-sweep investigation ruled out every candidate upstream cause:
- The server boots correctly under `bash start.sh` and registers all blueprints; `API_PREFIX` matches verbatim between `workspace/implementation/constants.py` and `test_helpers/constants.py` (`/concussion-program`), and the clock endpoint `POST /_clock/set_current_utc` responds on a manual boot.
- `test_suite/conftest.py` has a single trivial `api` fixture with no server-side preconditions, so there is no fixture-ordering or shared-state hazard capable of erroring all 117 setups.
- The earlier universal-setup-error signature is exactly what a reaped sweep produces: the tests' `ApiClient` defaults to `http://localhost:10000` and every request fails with connection-refused/`RemoteDisconnected` the instant the runner's per-test server is gone. Re-running the sweep under `setsid nohup` (as prescribed) produced zero setup errors.

Two diagnostic notes worth recording for future runs on this task:
- Do **not** try to shortcut with a single shared server (`API_BASE_URL` + plain pytest). Doing so yields ~114 spurious failures purely from cross-test contamination — the suite reuses fixed unique keys (`market_code` `HCK`, `license_number` `LIC-1001/2001/3001`, `jersey_number` 24), so the second test onward hits `ERR_UNIQUENESS_VIOLATION`. `--isolation per-test-server` is load-bearing here, not a preference.
- Beware `pkill -f` with patterns like `app.py` or a script name in this environment — the pattern matches the invoking shell's own command line and kills the calling Bash session (observed exit 144). Kill by port (`fuser -k -n tcp <port>`) instead.

Incidental cleanup: removed the `__pycache__` directories generated during diagnosis. No files in `test_suite/`, `test_helpers/`, or `workspace/implementation/` were modified.

### Orchestrator verification note

The orchestrator independently re-read all 8 `results.*.json` (each `117/117 passed, 0 failed, 0 errors`) and confirmed via mtimes that every file in `test_suite/`, `test_helpers/`, and `workspace/implementation/` still carries its generation-time timestamp (09:36–10:03) — i.e. zero bytes changed during Step 7. Test-file count is unchanged (15 `test_*.py` + `conftest.py`), confirming zero deletions.

### Step 8 skip decision

Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. Per the skill's Step 8 skip condition, `PRD.md` already determined every behavior the implementation exhibits at the sites the tests exercised, so **Step 8 is skipped** and no `PRD_FINALIZED.md` is produced. Step 9 therefore starts from `workspace/PRD.md`.

## Step 8: Finalize PRD — 2026-09-02T13:15:00.000Z

SKIPPED per the skill's Step 8 skip condition. Step 7 exited on its first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes, so there was no `<step_7_diff>` to hand off and no PRD-silence/mismatch site for Step 8 to target. No `workspace/PRD_FINALIZED.md` was produced; Step 9 sourced `workspace/PRD.md` directly.

## Step 9: Complete PRD — 2026-09-02T13:24:00.000Z

Done. `PRD_COMPLETED.md` written.

## Source vs completed
| | lines | chars |
|---|---|---|
| `workspace/PRD.md` | 529 | 92,074 |
| `workspace/PRD_COMPLETED.md` | 529 | 96,615 |

Char delta **+4,541** (net +4,509 body chars). 18 lines revised in place; **no new lines, paragraphs or sections** — every change is an in-paragraph insert or rewrite.

## Counts
- **ambiguity-pins: 19**
- **mismatch-revisions: 6**

## Changes
- §2.2 Success envelope — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not wall-clock time — `response.py:22`
- §2.5 rung 3 — insert — ambiguity — unrecognised body keys are ignored, not refused — `validation.py:37`
- §2.5 rung 3 — insert — ambiguity — absent/empty body is treated as `{}` (required fields then report missing) — `validation.py:22`
- §2.5 rung 3 — insert — ambiguity — `market_code` shape and a `ClubPhysician`'s disallowed `trigger_source` are decided at this rung — `reference.py:27`, `evaluations.py:48`
- §2.5 rung 10 — **revise** — **mismatch** — return-to-contact also defers `STAGE_FROZEN` to rung 11 (was "`PENDING_INC_CLEARANCE` only"), so it yields `ERR_CASE_STAGE_FROZEN` — `cases.py:353`
- §2.6 — insert — ambiguity — `expected_player_version`/`expected_case_version` validated as integers >= 0, no upper bound — `baselines.py:26`, `cases.py:210`
- §2.8 posture routine — **revise** — **mismatch** — club `version`/`updated_at` (and each case's) advance only when the routine actually changes a derived figure; an identical findings re-issue leaves both untouched — `posture.py:47,76`
- §2.12 — insert — ambiguity — integer filters are unbounded except `stage_index` (1-5); id filters matched literally with no existence check; `auto_opened` accepted spellings — `validation.py:163,178,187`
- §3.3 — insert — ambiguity — a `ClubPhysician` declaring `UNAFFILIATED_OBSERVER` is refused `ERR_INVALID_REQUEST`; an observer may declare all five triggers — `evaluations.py:48-51`
- §3.3 — **revise** — **mismatch** — on-field clearance mutates no player field, so the player row is untouched and its `version` does not advance — `evaluations.py:310-314`
- §3.5 — insert — ambiguity — diagnosis answers `201` with the newly created case, not the evaluation — `evaluations.py:238`
- §3.7 — insert — ambiguity — `decision` and `decision_notes` both required, notes non-empty — `cases.py:272-273`
- §3.7 — **revise** — **mismatch** — a denial on a case a sanction left `STAGE_FROZEN` applies its ladder consequences but leaves `case_status` frozen; `/decide` has no freeze guard — `cases.py:302-307`
- §3.7 — insert — ambiguity — "most recent clearance" = greatest `requested_at`, ties by later `created_at` then insertion order — `cases.py:35-39`
- §3.7 — insert — ambiguity — a null `earliest_return_at` fails with `ERR_RETURN_BEFORE_EARLIEST_DATE` — `cases.py:359-361`
- §3.7 — insert — ambiguity — return-to-contact `documentation_note` is validated but not persisted — `cases.py:347`
- §3.7 — **revise** — **mismatch** — `cases_cleared_count` bump refreshes the consultant's `updated_at` but does **not** advance its `version` — `cases.py:397-400`
- §3.7 — insert — ambiguity — `frozen_from_status` is reset to null on clearance for contact — `cases.py:382`
- §3.8 — insert — ambiguity — `days_since_diagnosis` derived per read and floored at 0 for a wound-back clock — `calc.py:136-141`
- §3.8 — **revise** — **mismatch** — the 21-day sweep transition bumps the player's `version` only where `availability_status` actually changed — `sweep.py:96-99`
- §3.8 — insert — ambiguity — the roster-exemption grant takes no body fields and returns `200` with the case — `cases.py:405-408`
- §3.9 — insert — ambiguity — latest-case tie-break for the designation window, and it requires a non-null `cleared_for_contact_at` — `calc.py:81-82`
- §3.9 — insert — ambiguity — a late-filing audit is minted already `FINDINGS_ISSUED` at `version` 1 with null issuer/`sideline_evaluation_id`, and is exempt from the season fine cap — `services/audits.py:37-52`
- §3.10 — insert — ambiguity — `closing_note` is among the null-on-open audit fields — `services/audits.py:23`
- §3.11 — insert — ambiguity — sweep-opened audits likewise born at `version` 1 and cap-exempt; `swept_at` is the logical clock; summary returned `200`/`object` — `sweep.py:38,112`

Notable finding worth flagging: §2.5 rung 10 and §3.10 were internally contradictory in the source PRD about return-to-contact on a `STAGE_FROZEN` case; the implementation follows §3.10 (`ERR_CASE_STAGE_FROZEN`), and the ladder text now says so.

### Orchestrator verification note

`workspace/PRD_COMPLETED.md` exists, is 529 lines / 96,615 chars, and ends on the complete error-code table (no truncation). `diff` against `PRD.md` reports 36 changed lines — exactly the 18 in-place line revisions claimed, with zero net line growth, confirming the minimal-patch discipline (no new sections or paragraphs).
