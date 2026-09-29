# Worklog — task_2606_newborn_hearing_screening_follow_up_tracking

## Step 1: Create task directory — 2026-09-03T18:32:06.975Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2606_newborn_hearing_screening_follow_up_tracking` and its `workspace/` subdirectory. Index 2606 was pre-assigned by the orchestrating command; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-03T20:10:00.000Z

All three artifacts are complete and verified.

**Files** (in `/home/ubuntu/github/CodingPRD/tasks/task_2606_newborn_hearing_screening_follow_up_tracking/`):

| File | Lines | Bytes | Top-level keys |
|---|---|---|---|
| `SCAFFOLD.yaml` | 3040 | 165,179 | `scenario`, `domain_name`, `api_prefix`, `complexity_profile`, `response_envelope`, `entities`, `state_machines`, `concurrency_rules`, `calculations`, `validations`, `endpoints`, `errors`, `roles` (no design keys — correct) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1681 | 111,313 | `scaffold_difficulty_design` only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3958 | 256,999 | `scaffold_corner_design` only |

**SCAFFOLD.yaml counts:** 13 entities, 54 endpoints (25 reads / 29 writes), 10 state machines, 10 calculations, 42 validations, 57 errors, 7 roles, 2 concurrency rules.

**Design instances:**
- §1.8 difficulty: **18** instances (9 rules × 2 instances each).
- §1.9 corner: **79** instances across all nine guide sections — **65** with a full `test_recipe` plus **14** `excluded_because` stubs pointing at the §1.8 instance that already covers the corner. Section census: entities 11, state_machines 16, calculations 13, validations 9, endpoints 6, errors 14, rbac 4, cross_cutting_complexity_layers 5, consistency_model 1.

**Lint:** `scaffold_lint.py` re-run after the final SCAFFOLD.yaml comment fix (§1.5 header now correctly says "54 endpoints … 29 writes"):
```
§1.5 endpoints declared: 54   §1.1 entities declared: 13
§1.8 instances scanned:  18   §1.9 instances scanned: 65
Calls scanned (§1.8+§1.9): 937
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Notable fix during generation: ten §1.9 setup chains hardcoded `expected_infant_version: 2`, violating the OCC rule that the field must be a captured `${var}`; each now does a preceding `GET /infants/{id}` capturing `$.data.version`. The hard constraint held — no sibling task directory was listed, read, or grepped; the scaffold derives only from the scenario text plus the skill spec and its claim-extraction guide.

## Step 3: Copy shared files — 2026-09-03T20:10:51.526Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T20:26:30.000Z

PRD generation is complete and verified.

**Output:** `workspace/PRD.md` — **453 lines** (109,962 bytes), built with 10 chunked `cat >>` heredoc appends (no single giant Write).

**Section list**
- `# Newborn Hearing Screening API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Program Actors and Role-Based Access Control · 2.2 API Response Structure (verbatim skill block, incl. both `#### Standard ... Format` sub-headings) · 2.3 Pagination · 2.4 Registry Record Properties · 2.5 The Logical Program Clock · 2.6 Corrected Versus Chronological Age: the Dual Basis · 2.7 Milestone Benchmarks and Timeliness Classification · 2.8 Precision and Rounding · 2.9 Cascade Integrity and Conservation Invariants · 2.10 Optimistic Concurrency Control · 2.11 Request Validation Order (all 42 priority bands)
- `## 3. Business Logic & Workflows` — 3.1 Facilities, Providers and Clinic Capacity · 3.2 Registering a Newborn and the Out-of-Hospital Capture Pathways · 3.3 The Physiologic Screen and the Pass / Refer Fork · 3.4 Follow-Up Episodes: Scheduling, Attempts, Loss and Re-Engagement · 3.5 Family Navigation, Interpreter Support and the Support Budget · 3.6 Diagnostic Audiologic Evaluation: Submission, Attestation and Finalization · 3.7 Early Intervention Referral, Program Placement and Enrollment · 3.8 The Delayed-Onset Risk Registry and Loss-to-Follow-Up Risk Scoring · 3.9 Provider Reporting Compliance, Penalties and the Period-Close Checkpoint
- `## 4. Endpoint Definitions`
- `## 5. Error Code Catalogue` ← **last heading in the file**; document ends on the final error-table row, not mid-sentence.

**Verification counts**
- Endpoints documented: **54 / 54** (grep of every scaffold path against the doc; `## 4` table has exactly 54 rows)
- Errors documented: **57 / 57** in §5, and **0** of the 57 appear only in the table — every error id is also motivated in §1–§4 prose
- Entities documented: **13 / 13**
- Enum values: **0** missing; state-machine states: **0** missing; transition targets: **0** missing; all 10 state machines and all 10 calculations covered
- No pseudocode leakage: zero occurrences of `>=`, `<=`, `min(`, `max(`, `+=` in the document; no fuzzy quantifiers (the one "roughly" I found was rewritten to "exactly 180 days / exactly 270 days")

**Hard Contracts**
- **Contract 1 (Field-Name Coverage): PASS** — mechanically diffed the authoritative required set of **148** names (all entity fields + all endpoint `input` names with `?` stripped + all inline output-shape keys) against the 402 distinct backticked tokens in the doc: **0 missing**.
- **Contract 2 (Rule Coverage): PASS** — all 42 validations present with their exact error ids and the first-failing-check ordering, plus worked precedence examples; both OCC rules (`expected_infant_version` → `ERR_STALE_INFANT_VERSION`, `expected_facility_version` → `ERR_STALE_FACILITY_VERSION`, both 412); both cascades (confirmed-loss finalization C1 and the close-run escalation C2) written end to end including the sibling branches that mint nothing; both dual-variant calculations (applied vs chronological age basis; cohort vs encounter performance score, with the 45.00 / 70.00 contrast and the null-denominator rules); the penalty tier keyed on base+carryover with the surcharge applied to base only and a single half-up rounding; conservation invariants for slot capacity and navigation budget; `created_at ASC` determinism at every sweep.
- **Contract 3 (§3 Path Purity): PASS** — scanned every backticked token between `## 3.` and `## 4.`: **0** tokens start with `/`, **0** are bare HTTP methods, **0** combine method+path. §3 refers to operations only by state transition, role+gerund, or capability.

Constraints honoured: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was read. No audit footer was written into PRD.md — it ends at §5.

**Orchestrator anti-truncation check:** independently ran `tail -25` and `grep -n '^#'` on PRD.md. The file terminates on the final row of the §5 error table (`| ERR_NAVIGATOR_AT_CAPACITY | 409 |`), a real section boundary, and the heading list runs contiguously §1→§5 with no gap. Not truncated; no regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T22:05:00.000Z

Queue A is now complete; the full suite is written, compiles, and passes every self-check.

## Files written (all at the task root, nothing under `workspace/`)

`test_helpers/` — 10 files, unchanged from Stage 1: `__init__.py` 1, `api_client.py` 463, `api_errors.py` 148, `assertions.py` 217, `clock.py` 56, `constants.py` 224, `factories.py` 277, `fixtures.py` 773, `test_users.py` 101, `types.py` 131.

`test_suite/` — 21 files, 5,377 lines: `conftest.py` 24; `test_01` 479, `test_02` 446, `test_03` 470, `test_04` 178, `test_05` 250, `test_06` 432, `test_07` 280, `test_08` 344, `test_09` 400, `test_10` 239, `test_11` 154, `test_12` 243, `test_13` 299, `test_14` 297, and new this session: `test_15_transitive_cascades.py` 312, `test_16_priority_pair_conflicts.py` 287, `test_17_boundary_precision.py` 263, `test_18_cross_entity_state_gates.py` 224, `test_19_resource_temporal_overlap.py` 294, `test_20_compensating_invariants.py` 262.

## Test counts per queue

- **Queue A (Difficulty)**: 36 tests over all 18 instances (9 rule_ids × 2 instances), exactly 2 tests per instance.
- **Queue B (Corner)**: 65 tests over all 65 non-stub instances.
- **Total 101 tests**, 83 distinct design instances tagged.

## Skipped design instances

**None.** Every non-stub instance in both indices is translated. The only untranslated corner entries are the 14 that carry `excluded_because` (stubs whose names end `_covered_by_difficulty_design`); they are correctly absent.

## Design-tag verification

An AST pass over all 21 files confirms: every `test_*` function has a docstring, exactly one `Design:` line, that line is the **last** non-blank docstring line, the queue prefix is `Difficulty/` or `Corner/`, and every referenced instance name exists verbatim in the source yaml. Zero problems. A second pass whitespace-normalises every `PRD: "…"` quote and greps it against `workspace/PRD.md` — all 101 quotes are verbatim-present (one pre-existing elided quote in `test_03` was repaired to the full line-96 sentence). `python3 -m py_compile` passes on all 31 generated `.py` files; no duplicate test names; no scaffold vocabulary leaks into emitted text; `__pycache__` removed.

## Recipe bugs corrected against the PRD (PRD-first)

- `resource_temporal_overlap/family_burden_buffer_…`: the recipe supersedes an `ESCALATED_DIAGNOSTIC` episode, which PRD line 216 forbids ("the named episode must itself be in `PENDING_SCHEDULING` or `SCHEDULED`"). I re-derived the setup — the rescreen **passes**, so the appointment is `ATTENDED` and the episode `RESOLVED_PASS`, then a fresh `RESCREEN` episode is opened — preserving the instance's asserted outcome exactly (11 h apart → 409 `ERR_FAMILY_BURDEN_BUFFER`; exactly 86400 s → 201).
- `cross_entity_state_dependency/infant_screening_status_gates…`: the recipe's final assert claims a successful submit moves the infant to `DIAGNOSTIC_IN_PROGRESS`; PRD line 252 gives submit no infant-status effect, so the test asserts the infant stays `REFERRED`.
- `boundary_precision_check/diagnostic_benchmark_day_90…`: the recipe calls a 39-week infant's `prematurity_offset_days` 0; PRD line 102 makes it 7 (corrected age 84 at 91 chronological days). The basis is still `CHRONOLOGICAL`, so the day-90/day-91 verdicts are unaffected.

**Orchestrator layout check:** `test_helpers/` and `test_suite/` both land at the task root; `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/`. No relocation needed.

## Step 6: Generate implementation — 2026-09-03T21:35:00.000Z

Implementation complete.

## Files written (`workspace/implementation/`)

| File | Lines |
|---|---|
| `start.sh` (chmod +x, guarded pip, `exec python3 app.py`) | 8 |
| `requirements.txt` | 1 |
| `app.py` (app factory, blueprint registration, ApiError/404/405/500 envelope handlers, `0.0.0.0:$PORT` default 10000) | 64 |
| `db.py` (in-memory `store` of 13 dicts, logical clock pinned at `2026-08-01T00:00:00Z`, `_seq` tiebreak, per-request dirty/fresh version bumping) | 168 |
| `errors.py` (58 spec error ids + status map) | 92 |
| `response.py` (`{meta,response_type,data}` envelopes, pagination guard) | 105 |
| `middleware.py` (priorities 1, 2, 7 — header auth, RBAC, entity-backed identity) | 95 |
| `validate.py` (all enum sets + schema helpers, priority 3) | 179 |
| `resolve.py` (priority 5/6 path + pinned FK-order resolution) | 54 |
| `calc.py` (dual age basis, timeliness, LTF risk, selectors, tiered penalties, dual performance score, derived counts) | 447 |
| `services.py` (episode/task/referral/risk cascades, budget reservation, travel buffer, re-engagement) | 221 |
| `serialize.py` (13 serializers, derived-on-read fields) | 236 |
| `routes/__init__.py` | 17 |
| `routes/facilities.py` (8 endpoints) | 161 |
| `routes/infants.py` (8) | 236 |
| `routes/encounters.py` (3) | 210 |
| `routes/followup.py` (11) | 269 |
| `routes/diagnostics.py` (11) | 341 |
| `routes/navigation.py` (5) | 195 |
| `routes/compliance.py` (8) | 384 |
| **total** | **3483** |

## Endpoint count
**54 / 54** — verified by enumerating `app.url_map` (excluding HEAD/OPTIONS), matching the PRD §4 table exactly. All `.py` files pass `python3 -m py_compile`; `__pycache__` removed.

## Smoke test
Launched `PORT=41606 bash start.sh`, ran a 30-assertion birth-to-enrollment script, then killed by PID (port 41606 confirmed free afterwards; no pattern kills used). Result: **0 failures**. Verified live: facility/provider/infant creation, `REFER` birth screen with derived `overall_result` and the C3 rescreen-episode cascade, operator navigation task with unit debit (40→38) and completion, diagnostic submit → self-attest rejected with `ERR_SEGREGATION_OF_DUTIES` → second-reader attest → `FINALIZED_LOSS` six-link cascade (referral placed at the regional EI program, `EI_LINKAGE` task auto-assigned to the sole eligible navigator), referral ACCEPT + enroll (`ei_timeliness_status=ON_TIME`, age 12), logical clock move via `to_iso8601`, period overlap rejection (`ERR_PERIOD_OVERLAP`), report filing with computed actuals, and the full close run (2 facilities assessed, auto-generated non-filing report assessed 6 = round_half_up(5 × 1.25), late filed report assessed 3, dashboard rates and null-denominator scores). Error surface checks returned `ERR_UNAUTHENTICATED` 401, `ERR_INFANT_NOT_FOUND` 404, `ERR_INVALID_PAGINATION` 400. A fresh relaunch confirmed an empty store (`total_count=0`) and the clock back at `2026-08-01T00:00:00.000Z`, as required by `--isolation per-test-server`.

Two notable spec ambiguities resolved from PRD + SCAFFOLD only (no test files were read or written): an interpreter-flagged booking with a short budget is **rejected** with `ERR_NAVIGATION_BUDGET_EXHAUSTED` (validation #40 lists `POST /rescreen-appointments`), and `assign-program` is gated on `ei_program_facility_id is null` (validation #13) rather than on referral status.

## Step 7: Run tests and iterate — 2026-09-03T22:07:39.880Z

Green across all 8 parallel rounds: **102/102 passing in every round**.

## Summary

**Iterations run:** 2 sweeps (1 diagnostic + 1 confirming). Iteration 1 was fully deterministic — the identical 11 failures in all 8 rounds, no flakiness anywhere.

**Tests deleted (assertions removed, PRD-silence category):**
- `test_09_access_control_and_validation_order.py::test_the_role_check_fires_before_the_body_is_validated` and `::test_every_exclusive_operation_is_refused_to_the_wrong_role` — trailing `client.list_facilities(...)` no-side-effect assertions. **STEP 1a PRD SILENT**: PRD §4 documents 54 endpoints and `GET /facilities` is not among them (nor is it in SCAFFOLD); the tests were asserting against an endpoint that no PRD-only implementer could know exists. The covered assertions (403 `ERR_FORBIDDEN_ROLE`) were kept per STEP 1c.
- `test_07::test_the_critical_band_opens_at_exactly_forty_five_points` — `ltf_risk_score=41, priority_band="HIGH"` on the *pre-registration* timeliness-panel read. **STEP 1b COMPUTED-FIELD SILENCE**: §3.8 defines `ltf_risk_score` as an infant field "recomputed by every transition whose narrative says risk is recomputed" and enumerates only write transitions; a GET is not one. Echoing the stored value (29, last recomputed before the clock moved) and recomputing at read time (41) are both faithful. The test's post-registration assertions (45/`CRITICAL`, agreeing under both readings) were kept.
- `test_17::test_the_late_verdict_changes_the_paperwork_and_nothing_else` — `ei_timeliness_status=None`, and `test_10::test_the_timeliness_panel_derives_the_corrected_basis_for_a_nicu_stay` — `ei_timeliness_status="PENDING"`. **STEP 1b DEFAULT-VALUE SILENCE, proven by contradiction**: both infants have no `EarlyInterventionReferral`, yet the two tests demanded opposite panel values for the identical precondition. PRD says only "the early intervention figure being the enrollment timeliness of its referral" and never states what the panel shows when no referral exists.

**Fixes applied to `test_helpers/`:**
- `assertions.py` — `assert_episode_state()` gained a `timeliness_status` kwarg. `test_15` passed it and the helper raised `TypeError`; PRD line 226 states the loss transition writes "`timeliness_status` `OVERDUE`" verbatim, so the assertion is PRD-covered and the helper was simply missing the parameter.

**Fixes applied to `test_suite/` (test bugs, all made the test *more* faithful):**
- `test_16` ×3 and `test_09` ×1 — `body["data"]["error_id"]` / `body["data"]["message"]` / `body["meta"][...]` on the return value of `assert_error_envelope()`, which returns the already-unwrapped `data` dict, not the envelope. Corrected to `body["error_id"]` / `data["message"]`, with `meta` read from `response.json()`.
- `test_07::test_cleared_entries_leave_the_score_without_leaving_the_registry` — asserted `surveillance_recorded_at == clock.at(hours=5)` (the encounter's `performed_at`). PRD line 286: entries clear "with `surveillance_result` `PASS` and `surveillance_recorded_at` **at the logical clock**", which was 06:00. Corrected to `clock.at(hours=6)`.

**Fixes applied to `implementation/`:**
- `routes/infants.py::infant_timeliness` — the panel echoed each milestone's stored status unconditionally, so a 72-day-old infant with an open `INITIAL_SCREEN` episode reported `screening_timeliness_status: PENDING`. Per §2.6 ("The reference instant is the logical clock for a **live read**, and the milestone's own instant for a stored status") plus §2.7's incomplete-milestone rule, the panel now classifies at the logical clock when the milestone is not yet complete (episode still in the active set / evaluation not finalized / referral not enrolled) and keeps the stored, milestone-instant status once it is. That preserves `test_12`/`test_17`'s point that two babies read at one clock still carry divergent stored `ON_TIME`/`LATE` diagnostic verdicts.

No assertion was weakened to an HTTP-status check, no `skip`/`xfail` was added, no PRD-required implementation check was removed, and no data is seeded at startup.

**Orchestrator verification of the sweep artifacts** (per the known failure mode where a Step 7 agent claims a clean sweep without leaving evidence): independently read all 8 `workspace/implementation/results.$i.json`. Every round reports `passed=102 total=102 failed=0`. File mtimes are 22:01:06, later than the last test-file edit (21:54:38), confirming the green sweep ran *after* all fixes rather than being a stale pre-fix artifact.

## Step 8: Finalize PRD — 2026-09-03T22:18:37.892Z

Done. One consolidated edit.

## Line counts
- `PRD.md`: 453 lines / 109,962 bytes
- `PRD_FINALIZED.md`: 455 lines / 111,574 bytes (+2 lines, **+0.44%**; +1,612 bytes). Tail verified — ends on `| ERR_NAVIGATOR_AT_CAPACITY | 409 |`, same as `PRD.md`.

## Changes
- **§2.6 (per-infant timeliness panel paragraph, after PRD.md line 108)** — *insert* — new paragraph pinning how the panel resolves each of its three milestone figures (which row is consulted, stored-status vs live-classification-at-the-logical-clock, the benchmark/basis used for each live figure, and the value reported when no such row exists at all), plus the fact that `ltf_risk_score` / `priority_band` are echoed from the infant row rather than re-derived at read time — `implementation/routes/infants.py:164-220` (helpers `calc.timeliness` at `calc.py:71`, `calc.OPEN_EPISODE_STATUSES` at `calc.py:23`, `db.latest` at `db.py:108`).

## Per-edit pre-edit search log

**Edit 1 — §2.6 panel paragraph**
- (a) **Subject**: the `GET /infants/{id}/timeliness` panel's four milestone status fields (`screening_timeliness_status`, `diagnostic_timeliness_status`, `diagnostic_timeliness_status_chronological_basis`, `ei_timeliness_status`) plus the panel's `ltf_risk_score`/`priority_band`; equivalently, every place a timeliness status or a risk score reaches a response.
- (b) **Paths enumerated** (grepped `timeliness|OPEN_EPISODE_STATUSES|db.latest|ltf_risk|priority_band` across `implementation/`, then read each hit): `routes/infants.py:164-220` (the panel itself — the Step 7 site); `calc.py:71` `timeliness()`; `calc.py:43-64` `age_parts`; `calc.py:221-261` `ltf_risk`; `services.py:9-15` `recompute_risk` (only mutator of score/band); `services.py:19-37` `create_episode` (seeds `timeliness_status="PENDING"`, never null); `services.py:40-43,70-78` `write_episode_timeliness`/`close_episode`; `services.py:171-187` `mint_referral` (seeds `ei_timeliness_status="PENDING"`); `routes/encounters.py:129,152` (episode closures that write timeliness); `routes/diagnostics.py:63-71,160-176` (finalize writes both stored variants at `finalized_at`); `routes/diagnostics.py:290-318` (enroll writes `ei_timeliness_status` at `ifsp_date`); `routes/compliance.py:312-336` (close-run sweep writes `OVERDUE`, loss cascade); `routes/followup.py:96` (episode list filter on `timeliness_status`); `serialize.py:94-108,137-171` (episode/evaluation/referral echo stored statuses); `serialize.py:51-72` (`serialize.infant` echoes stored score/band); `routes/facilities.py:90-113` (performance dashboard — unrelated `report_timeliness_rate`, confirmed disjoint).
- (c) **Wording adjustments made**: (1) said "the panel reports the status stored on that row, **whatever it currently carries**" instead of "as written at the milestone's own instant", because an episode that left the active set as `SUPERSEDED`/`CLOSED_DECLINED` still carries the creation-time `"PENDING"` (`services.py:32`) that no milestone instant produced; (2) explicitly covered the "no such row exists" case (impl live-classifies, so a >30-day-old baby who passed at birth reads `OVERDUE`), rather than leaving it to be read as null; (3) added the parenthetical that a `DIAGNOSTIC` episode is never the screening figure's source, matching the type filter at `routes/infants.py:173-175`; (4) phrased the tie-break as "ties never broken by identifier" to stay consistent with §2.9's global ordering rule and `db.sort_rows`' `_seq` tiebreak.

## Step 7 items that needed **no** PRD change
- `GET /facilities` (test_09 deletions): the implementation has **no** such route (`routes/facilities.py` defines only `POST /facilities`, `GET /facilities/{id}`, `.../providers`, `.../performance`, `.../penalty-adjustments`), so PRD's omission already matches impl.
- `assert_episode_state(timeliness_status=…)` helper fix: PRD line 226 already pins `OVERDUE` at loss, and `routes/compliance.py:324-325` writes it — pure helper gap.
- test_16/test_09 error-envelope unwrapping fixes and test_07's `surveillance_recorded_at` fix: pure test bugs; PRD §2.2 and line 286 ("at the logical clock") already determine the behavior the impl exhibits.

Note (out of scope, not edited): `close_period` checks `ERR_EARLIER_PERIOD_OPEN` before `ERR_PERIOD_NOT_ENDED` (`routes/compliance.py:365-372`), the reverse of §2.11's ordering. Not a Step 7 item, so left alone. **Orchestrator note:** this is exactly the kind of residual mismatch Step 9's full scan exists to resolve; it is carried forward to Step 9 rather than hand-patched here.

## Step 9: Complete PRD — 2026-09-03T22:41:22.303Z

**Orchestrator decision (recorded per the autonomy directive):** Step 9 was run as **three sequential file-partitioned passes** over the 20-file implementation rather than one scan. A single pass over an implementation this large routinely returns a `PRD_COMPLETED.md` byte-identical to its source (the scan never actually reaches the later files), which is a silent no-op. Each pass edited `PRD_COMPLETED.md` in place, additively; pass 1 did the initial `cp` from `PRD_FINALIZED.md` and passes 2–3 were explicitly forbidden to re-copy or reset it.

### Pass 1 — core modules (app.py, start.sh, requirements.txt, db.py, errors.py, response.py, middleware.py, validate.py, resolve.py, serialize.py)

`cp PRD_FINALIZED.md PRD_COMPLETED.md` ran first. PRD_FINALIZED.md 455 lines / 111,574 chars → PRD_COMPLETED.md 455 lines / 114,714 chars (**+3,140 chars**, 11 lines revised in place, no new paragraphs/sections). Pins: **8 ambiguity, 3 mismatch**.

- §2.1 — revise — ambiguity — a header present but empty string counts as omitted → `ERR_UNAUTHENTICATED` — `middleware.py:48-51`
- §2.2 (`api_request_id`) — insert — ambiguity — shape pinned as `req_` + exactly 20 chars from `A`–`Z`/`0`–`9` — `response.py:10,19-20`
- §2.2 (`api_request_timestamp`) — insert — mismatch — read from the host's real clock, not the logical clock, and never compared to anything — `response.py:26` / `db.py:71-72`
- §2.3 — insert — ambiguity — non-integer pagination values → `ERR_INVALID_PAGINATION`, empty-valued param treated as omitted, `offset` unbounded above; boolean query filters accept `true`/`1`/`false`/`0` case-insensitively and ignore anything else — `response.py:73-98`, `validate.py:170-179`
- §2.4 — insert — ambiguity — output always `…Z` with 3 fractional digits; `created_at`/`updated_at` stamped from the logical clock; inbound instants accept `Z`/`z`, numeric offsets (normalised to UTC), zone-less (read as UTC), any fractional precision, else `ERR_INVALID_REQUEST` — `db.py:60-87,114-125`
- §2.5 — revise — mismatch — "does not read the host's wall clock" scoped to program logic, with the envelope timestamp named as the sole exception — `db.py:71-72`
- §2.9 — insert — mismatch — `version` bumps once per request rather than once per touch, `updated_at` set once to the logical-clock instant, rows created by the request returned at `version` 1 with `updated_at == created_at` — `db.py:114-167`
- §2.9 — insert — ambiguity — equal-`created_at` rows order by insertion sequence; "most recently created" = last inserted among the greatest `created_at` — `db.py:103-111`
- §2.11 step 3 — insert — ambiguity — JSON `null` treated as absent (optional → default, required → `ERR_INVALID_REQUEST`); absent body read as `{}`; unparseable or non-object body → `ERR_INVALID_REQUEST` — `validate.py:72-92`
- §4 intro — insert — ambiguity — trailing slash tolerated on every path (`strict_slashes = False`) — `app.py:19`
- §5 intro — insert — ambiguity — three envelope-level fallbacks outside the numbered order and the table: `ERR_NOT_FOUND` 404 (unknown path), `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500 — `app.py:28-53`, `errors.py:73-75`

Verified-as-already-pinned: every `ERROR_STATUS` mapping matches §5 exactly; `resolve.FK_ORDER` matches §2.11 step 6 order and codes verbatim; all 40 enum sets in `validate.py` match their §3 declarations value-for-value; middleware role list, `ERR_FORBIDDEN_ROLE`/`ERR_IDENTITY_MISMATCH` split and the facility-scoped roles match §2.1; envelope/`has_more`/`total_count` semantics match §2.2–2.3; `serialize.py` field sets match §3 including the `ScreeningEncounter` no-`version`/no-`updated_at` exception.

### Pass 2 — calc.py, services.py, routes/facilities.py, routes/infants.py, routes/encounters.py

457 lines / 123,096 chars (**+2 lines, +8,382 chars**), 22 targeted Edits, all in-paragraph. Counts: **21 ambiguity, 1 mismatch**.

- §3.5 — revise — mismatch — the paragraph listed the booking's interpreter task among the cascade-minted tasks getting `units_reserved` 0 / `budget_shortfall_flag` true while also calling that booking rejectable; impl takes the reject path, so the cascade list now names only `EI_LINKAGE` and `OUTREACH_CALL` — `services.py:159-167`
- §3.5 — insert — ambiguity — operator-initiated tasks always carry full `units_reserved` and `budget_shortfall_flag` false — `services.py:150-156`
- §3.5 — insert — ambiguity — the booking's `INTERPRETER_SESSION` task straddles paths: operator funding rule, cascade assignment rule (empty pool leaves it `UNASSIGNED`, no `ERR_NO_ELIGIBLE_NAVIGATOR`) — `services.py:161-167`
- §3.4 — insert — ambiguity — every newly created episode starts `timeliness_status` `PENDING` — `services.py:32`
- §3.4 — revise — ambiguity — re-engagement restores the most recently created `LOST_TO_FOLLOW_UP` episode regardless of the infant's own state; only a `LOST_TO_FOLLOW_UP` infant advances and increments `reengagement_count` — `services.py:208-221`
- §3.8 — insert — ambiguity — a recompute landing on the same score/band writes nothing and does not bump `version` — `services.py:11-15`
- §3.8 — insert — ambiguity — no uniqueness on `risk_factor_code`; duplicates each count toward `risk_factor_count` — `infants.py:250`, `calc.py:145`
- §3.8 — revise — ambiguity — a `FacilityScreener` may also record a `SURVEILLANCE` encounter (no per-type role narrowing) — `encounters.py:22`
- §3.8 — revise — ambiguity — refer branch also stamps `surveillance_recorded_at`; stores literal `REFER` for `INCOMPLETE`; the `DIAGNOSTIC` episode is minted without §3.4's active-episode guard — `encounters.py:177-186`
- §3.3 — revise — ambiguity — `appointment_id` with no `episode_id` is itself `ERR_LINKAGE_MISMATCH` — `encounters.py:69-71`
- §3.3 — insert — ambiguity — pass branch closes every open `INITIAL_SCREEN` episode in `created_at` order; the whole birth/home cascade is gated on `NOT_SCREENED` — `encounters.py:119-131`
- §3.3 — revise — ambiguity — the `OUTREACH_CALL` task gets `episode_id` null when no new episode was opened, plus a second risk recompute after minting — `encounters.py:136-143`
- §3.3 — insert — ambiguity — episode cascade is linkage-driven not type-driven, fires only on `SCHEDULED`, never escalates a `DIAGNOSTIC`-type episode, four links in one fixed order — `encounters.py:106-164`
- §3.2 — insert — ambiguity — infant initial `discharge_datetime` null / `discharged_unscreened` false / `reengagement_count` 0; the two counts are derived not stored — `infants.py:70-77`
- §3.2 — insert — ambiguity — a contact-preferences PATCH supplying none of the four fields is accepted and still bumps `version` — `infants.py:126-135`
- §3.1 — insert — ambiguity — provider roster filters `provider_type` and `credential_status`, unvalidated exact-string match — `facilities.py:81-86`
- §3.9 — insert — ambiguity — `last_closed_period_label` is the two instants joined by two literal dots; dashboard rates/scores read back as stored, balance/posture derived live — `calc.py:445-447`, `facilities.py:95-112`
- §3.9 — insert — ambiguity — `actual_refer_count` spans all `encounter_type`s and is the one place `INCOMPLETE` is not folded into `REFER` — `calc.py:436-442`
- §3.9 — insert — ambiguity — rate nullity never propagates sideways; report timeliness rate is never null — `calc.py:379-401`
- §3.9 — insert — ambiguity — penalty-adjustment `reason` is mandatory non-empty but persisted nowhere — `facilities.py:56`
- §2.1 — insert — ambiguity — read endpoints check only that identity resolves, applying no facility-scope comparison, so a `FacilityAdmin` may read other facilities' rows — `facilities.py:69/78/94`, `infants.py:143`
- §2.5 — insert — ambiguity — the clock accepts any parseable instant including backward moves; the response body holds only `current_utc` — `facilities.py:155-161`

### Pass 3 — routes/followup.py, routes/diagnostics.py, routes/navigation.py, routes/compliance.py, routes/__init__.py

457 lines / 128,855 chars (**+5,759 chars**, line count unchanged), 18 targeted Edits, all in-paragraph. §-heading count (25 by the pass's count) and §5 row count (57) unchanged; no new sections or table rows. Counts: **12 ambiguity, 6 mismatch**.

Mismatch revisions:
- §3.9 (close run preconditions) — revise — mismatch — precondition order rewritten to `ERR_PERIOD_ALREADY_CLOSED` → `ERR_EARLIER_PERIOD_OPEN` → `ERR_PERIOD_NOT_ENDED` — `routes/compliance.py:363-370`
- §3.4 (appointment closure) — revise — mismatch — dropped the "a `NO_SHOW` may only be recorded once the slot's `starts_at` is at or before the logical clock" requirement; the impl applies no such check, `BOOKED`-ness is the only guard — `routes/followup.py:234-238`
- §3.7 (referral fields) — revise — mismatch — `resolution_reason` records the reason of any decision (rejection, family decline, or acceptance) — `routes/diagnostics.py:249-250`
- §3.7 (ACCEPT) — revise — mismatch — acceptance stores a supplied `reason` in `resolution_reason`, omission leaving the field as it stood — `routes/diagnostics.py:249-250`
- §3.9 (escalation cascade) — revise — mismatch — "whose posture became `PROBATION`/`SUSPENDED` in this run" → posture as observed after the facility's own assessment write, so already-degraded facilities are swept identically — `routes/compliance.py:277-279`
- §4 (`POST /ei-referrals/{id}/assign-program` row) — revise — mismatch — removed "or re-assign"; available only while the program is null, matching §3.7 — `routes/diagnostics.py:222-224`

Ambiguity pins:
- §3.4 — insert — administrative closure and supersession write no `timeliness_status`; only a resolving screen, diagnostic finalization, and the §3.9 sweep do — `routes/followup.py:53,75`
- §3.4 — insert — `reason` written to `disposition_reason` on both dispositions, null when omitted — `routes/followup.py:238`
- §2.10 — insert — `expected_facility_version` bounded at ≥1 (0/negative → `ERR_INVALID_REQUEST`) while `expected_infant_version` is unbounded (0/negative → `ERR_STALE_INFANT_VERSION`) — `routes/compliance.py:85-86` / `routes/followup.py:32`
- §3.7 — insert — `decision` role-gated from the body alone: a `Navigator` may send only `FAMILY_DECLINED` (`ERR_FORBIDDEN_ROLE` otherwise, ahead of referral resolution), an `EICoordinator` all three — `routes/diagnostics.py:238-239`
- §3.7 — insert — an unplaced referral has no facility to scope the coordinator's identity against, so any coordinator may reject it — `routes/diagnostics.py:241`
- §3.7 — insert — the three enrollment conditions tested in the written order (referral status → evaluation `FINALIZED_LOSS`, named as `ERR_EVALUATION_INVALID_STATE` → `ifsp_date` range) — `routes/diagnostics.py:296-302`
- §3.5 — insert — travel buffer precedes unit reservation for a named navigator but follows it on the `auto_assign` path, so budget exhaustion wins there — `routes/navigation.py:71-87`
- §3.5 — insert — an explicit `assigned_provider_id` overrides `auto_assign`; the selector is never consulted — `routes/navigation.py:77-80`
- §3.5 — revise — `closure_note` records the supplied `reason` on a completion as well as a cancellation — `routes/navigation.py:159-164`
- §3.6 — insert — exactly four checks on opening an evaluation; the episode's `episode_type`/`status`, the facility's `facility_type` and posture, and the infant's `screening_status`/consent are not checked at this step — `routes/diagnostics.py:46-54`
- §3.6 — insert — the supplied `note` replaces `attestation_note` outright, so an `ACCEPT` omitting it leaves the field null — `routes/diagnostics.py:132-139`
- §3.9 — insert — the period-`OPEN` test precedes the report's own status test — `routes/compliance.py:155-168`
- §3.9 — insert — filing is not gated on period state; a report may be filed against a closed period — `routes/compliance.py:89-116`
- §3.9 — insert — the escalation writes are unconditional, so an already-flagged episode is rewritten and re-counted; the cascade's `OUTREACH_CALL` task always carries `episode_id` null — `routes/compliance.py:291-308`

### Resolution of the two carried-forward items

1. **`compliance.py` close-period ordering** (flagged by Step 8 as out of its scope): resolved in pass 3. On inspection **§2.11 was already correct** — it places `ERR_EARLIER_PERIOD_OPEN` in the state band (10–15) and `ERR_PERIOD_NOT_ENDED` in the temporal band (26–31), i.e. earlier-period-open first, which is exactly what the impl does. The genuine mismatch was §3.9's narrative sentence, which listed the clock check first. §3.9 alone was revised; §2.11's numbered list is untouched.
2. **`resolve.TARGETS["risk_entry"] → ERR_RISK_ENTRY_NOT_FOUND`**: confirmed **dead code** across all three passes — no route resolves `risk_entry` (the registry sweep reads `store.risk_entries` directly and no endpoint takes a risk-entry path parameter). The PRD was correctly left alone; no §5 table row was added, so the document tail is undisturbed.

### Orchestrator verification

- `PRD_COMPLETED.md`: **457 lines / 128,855 bytes**, vs `PRD_FINALIZED.md` 455 / 111,574 and `PRD.md` 453 / 109,962.
- `cmp` against `PRD_FINALIZED.md` → **differs** (not the byte-identical no-op that indicates a scan never ran); the diff touches **90 lines**.
- Tail intact: ends on `| ERR_NAVIGATOR_AT_CAPACITY | 409 |`. 28 markdown headings, all **57** `ERR_` catalogue rows present. No truncation.
- No file under `workspace/implementation/`, `test_suite/`, or `test_helpers/` is newer than `results.1.json`, so Steps 8 and 9 changed documentation only — the 8/8 green sweep (102/102 per round) remains the true state of the code.

**PIPELINE COMPLETE.** Step 9 has written `workspace/PRD_COMPLETED.md`.
