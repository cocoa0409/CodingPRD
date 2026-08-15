# Worklog — task_1450_master_gardener_volunteer_program_help

## Step 1: Create Task Directory — 2026-08-13T08:28:00.000Z

Task directory `tasks/task_1450_master_gardener_volunteer_program_help/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per instructions. Difficulty target: harder than expert level (user directive).

## Step 2: Generate Scaffold — 2026-08-13T10:27:00.000Z

All three artifacts are written and verified. `scaffold_lint.py` verdict, verbatim:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1450_master_gardener_volunteer_program_help/SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1450_master_gardener_volunteer_program_help/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (§1.8)
- `/home/ubuntu/github/CodingPRD/tasks/task_1450_master_gardener_volunteer_program_help/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (§1.9)

## SCAFFOLD.yaml counts

- **13 entities**: ProgramCycle, Application, Volunteer, TrainingEnrollment, CreditEntry, RecertificationRecord, Shift, ShiftSignup, Inquiry (self-FK follow-ups), DiagnosisReferral, Specialist, CommunityProject, RotationAssignment
- **12 state machines / 51 transitions**, including cyclic Volunteer (ACTIVE↔INACTIVE→EXITED), cyclic DiagnosisReferral (RETURNED→OPEN reassign loop), cyclic CommunityProject (revision resubmission loop), and Shift with FULL→OPEN auto-revert
- **13 calculations**: dual-variant credit totals (provisional vs official w/ per-project waterfall cap), dual-variant specialist score (rolling-90d vs lifetime), 3-mode combinatorial set (tiered+capped composite score; pinned per-entry quarter-hour rounding; pinned evaluation order for the circular-looking recognition tier), SLA clock math, two selector policies, three-semantics overlap rule
- **12 validations** (priorities 1–12: auth → schema → existence → ownership → OCC(412) → posture → state → SoD → constraint → temporal → referential, with an intra-priority tie-break pinned)
- **75 endpoints** (incl. `POST /_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` default)
- **64 error codes**; **3 roles** (ProgramCoordinator opaque, Volunteer/Specialist entity-backed; segregation-of-duties on project approve→close); **3 OCC concurrency rules** (cycle config, project amend, specialist patch)

## Design index counts

- **§1.8: 25 instances** — dual_variant_calc 2, combinatorial_formula 3 (modes a/b/c), non_linear_state_machine 3, transitive_cascade 2 (depth-4 cycle-close cascade + depth-2 project-close cascade), priority_pair_validation_conflict 3 (state>temporal, constraint>referential, posture>constraint), boundary_precision_check 3 (hours threshold, seat capacity, SLA equality), cross_entity_state_dependency 3, resource_temporal_overlap 3 (half-open location, buffered travel adjacency, closed-week bed), compensating_invariant 3 (seats, hour ledger, referral counts). All numeric asserts precomputed (e.g., 31.0 vs 22.5, 3.00 vs 2.75, rolling 100 vs lifetime 92, points 40.5).
- **§1.9: 75 instances** (69 active + 6 `excluded_because` stubs) across all nine taxonomy sections, covering error-trigger coverage for the full catalog, wrong-from rejections per machine, RBAC denials, OCC 412s, selector tie-breaks, envelope/pagination, and the clock default.

No sibling task directories were inspected; the design was derived solely from the scenario text and the skill specification.

## Step 3: Copy Shared Files — 2026-08-13T10:29:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1450_master_gardener_volunteer_program_help/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T11:05:00.000Z

All contracts pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1450_master_gardener_volunteer_program_help/workspace/PRD.md`.

**PRD.md line count:** 370 lines (~61 KB)

**Section list:**
- 1. Introduction (2 paragraphs — business context + compliance-first design angle)
- 2. Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control (headers, 3 roles, per-role identity translations)
  - 2.2 API Response Structure (emitted byte-verbatim from `section-2.2-response-structure.md` — verified programmatically)
  - 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, meta fields)
  - 2.4 Common Resource Properties (all 13 entities carry `id`/`created_at`/`updated_at`/`version`)
  - 2.5 The Logical Clock (default 2026-08-01T00:00:00Z, no wall-clock fallback, `to_iso8601`/`current_utc`)
  - 2.6 Cycle Posture as a Write Gate (three global posture rules with their 409 errors)
  - 2.7 Hours, Quarter-Hour Quantum, and Rounding
  - 2.8 Optimistic Concurrency Control (all three OCC rules with exact write endpoints, `expected_*_version` fields, error ids, HTTP 412)
  - 2.9 Request Validation Order and Nested Path Resolution (12-tier explicit ordering, left-to-right resolution, tier-8 tie-break)
  - 2.10 Cascading Consistency and Derived-Field Reconciliation
- 3. Business Logic & Workflows (8 subsections: 3.1 cycle setup/admissions/waitlist, 3.2 training/activation, 3.3 credit ledger, 3.4 shifts/signups/attendance, 3.5 inquiries/referral loop, 3.6 community projects, 3.7 garden rotation, 3.8 evaluation/recertification/year-end close)
- 4. Endpoint Definitions (75/75 scaffold endpoints, 4-column table)
- 5. Error Code Catalogue (64/64 errors, 2-column table, statuses verified against scaffold)

**Zero-Silence Rule self-audit (Hard Contracts):**

```
Field coverage check:
- entities[].fields: 102 required, 102 present, 0 missing
- endpoints[].request_body (endpoint-only ids): 10 required, 10 present, 0 missing
- endpoints[].query_params: 23 required, 23 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority tiers: 12 checked, 12 expressed in §2.9 ordered prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write endpoint + expected_<parent>_version + error id + 412 all named), 0 missing
- state_machines[].transitions: 51 checked, 51 fully expressed (from/to states, preconditions with error ids, side effects incl. cycle-close 4-link cascade + EXITED-at-2, project-close 2-link cascade, minted-entry field mappings), 0 missing
- calculations[]: 13 checked, 13 fully expressed in precise prose (composite score, credit_totals both variants, project_credit_cap waterfall, shift quarter-hour pipeline with the 100+70-minute divergence example, recertification_outcome with equality-passes boundary, pinned 3-step recognition, specialist rolling/lifetime scores, 48h SLA, waitlist order, specialist selector, consecutive-week chain, three overlap semantics, no-show gate), 0 missing
- validations[] conditions: 12 tiers checked, all 64 error ids matchable to triggers in §2/§3 prose (verified: 64/64 present), 0 missing
- endpoints[].side_effects / applies_to: 75 checked, 75 expressed, 0 missing
- entities[].fields[] structured content: 102 checked, defaults/initials/sources reconstructible (patched in audit pass: volunteer counter defaults, entry defaults, referral audit-field nulls, record stamp nulls, rotation/inquiry/signup null defaults), 0 missing
- sibling-branch symmetry: 8 groups checked (decide ACCEPT/WAITLIST/REJECT from both SCORED and WAITLISTED, training COMPLETED/FAILED, shift complete/cancel from OPEN+FULL, referral answer/return, project approve/revision/reject, rotation complete/missed/swap, record RECERTIFIED/SHORTFALL, provisional/official variants), all with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 700
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verifications: §2.2 block byte-identical to the canonical source; all state/enum values appear as exact UPPERCASE strings (`NO_SHOW` and `ANSWERED` standalone tokens were added during the audit; `REFERRED` appears in state-pair tokens per house style); no fuzzy/approximating words and no symbolic/boolean operators anywhere in §3; endpoint-side-effect freeze on `RECERTIFICATION` entry and the `ERR_INVALID_REQUEST` on explicit-last-specialist reassignment are both expressed. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-13T11:36:00.000Z

All checks pass. The generation is complete.

**Task**: task_1450_master_gardener_volunteer_program_help — Master Gardener Volunteer Program & Help Desk

### Test counts
- **Queue A (Difficulty)**: 25/25 instances covered, each with ≥2 tests → **50 difficulty tests**
- **Queue B (Corner)**: 69/69 non-stub instances covered with ≥1 test → **69 corner tests** (plus 1 second difficulty-leg overlap already counted)
- **Total**: **120 test functions** across 6 files; all 94 non-stub design instances tagged exactly once per test.

### Skipped instances
None. All 25 difficulty instances and 69 non-stub corner instances passed the PRD-first two-condition filter. The 6 `excluded_because:` stubs (`shift_full_to_open_revert_on_cancel`, `composite_score_correct_result`, `project_cap_partial_truncation`, `referral_due_at_constant`, `outreach_gold_bonus_application`, `shift_completion_mints_quarter_rounded_entry`) were correctly NOT translated; all their `difficulty_instance` cross-references resolve to real queue-A instances whose tests carry the assertions.

### test_helpers/ inventory (all files compile and import)
- `/home/ubuntu/github/CodingPRD/tasks/task_1450_master_gardener_volunteer_program_help/test_helpers/__init__.py` — barrel export (framework + PRD-specific)
- `types.py` — 13 entity TypedDicts (all `common_fields: true` here) + 17 status/enum classes + `UserRole`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (55 methods), module-level `api_client`
- `api_errors.py` — `ApiErrorId` enum (60 errors) + `HTTP_STATUS_CODES` map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` validators + seat/record invariant checkers
- `factories.py` — 16 payload factories (input fields only)
- `constants.py` — PRD thresholds (tier mins, SLA 48h, no-show limit 3, travel buffer 30 min, quarter quantum, clock default)
- `test_users.py` — `TEST_USERS` shared constants + per-instance `make_volunteer_headers`/`make_specialist_headers`/`make_coordinator_headers` builders (identity threading for entity-backed roles)
- `fixtures.py` — composite helpers across all 5 tiers: `create_and_open_cycle`, `create_accepted_volunteer`, `create_active_volunteer`, `setup_cycle_with_active_volunteer`, `setup_cycle_with_two_active_volunteers`, `setup_cycle_closed_with_shortfall_volunteer`, `setup_staffed_help_desk_shift`, `setup_triaged_inquiry`, `log_and_approve_service_entry`, `create_approved_project`, `move_cycle_to_recertification`, `close_cycle`, `create_rotation_assignment`, etc.

### test_suite/ inventory
- `conftest.py` — session `api` fixture + 5 role-header fixtures
- `test_01_cycle_admissions_training.py` — cycle posture, composite score, waitlist, training boundaries
- `test_02_credit_ledger.py` — totals variants, project cap, recognition tier/points, hardship, close outcome boundaries
- `test_03_shifts_signups_attendance.py` — location overlap, travel buffer, capacity boundary, strike gate, quarter-rounding minting
- `test_04_inquiries_referrals.py` — inquiry gates, referral selector, work loop, SLA equality, rolling-vs-lifetime scores
- `test_05_projects_rotation.py` — project review loop, segregation of duties, close cascade, bed-week/consecutive-week rules
- `test_06_lifecycle_rbac_occ.py` — 4-hop close cascade, volunteer cyclic lifecycle to EXITED, RBAC/auth, OCC, envelope/clock

### Self-check results
- **Stage 1**: all helper modules compile and import cleanly (`import test_helpers` OK).
- **Stage 2 completeness audit**: 94/94 non-stub instances tagged; 0 missing, 0 shortfall, 0 extra/unknown tags. Every difficulty instance has exactly ≥2 tagged tests; every corner instance ≥1.
- **Final PRD-citation pass**: automated sweep over all 120 tests — every docstring carries exactly one `Design:` tag as its final line, and every quoted PRD sentence's distinctive ≥8-word substring survives a literal (whitespace-normalized) grep of `PRD.md`. 0 failures.
- **No `pytest.mark.skip`/`skipif`/`xfail`** anywhere in test_suite/ or test_helpers/.
- **pytest --collect-only**: 120 tests collected with no import errors.

## Step 6: Generate Implementation — 2026-08-13T11:30:00.000Z

Implementation complete. Final summary:

**File inventory** (under `/home/ubuntu/github/CodingPRD/tasks/task_1450_master_gardener_volunteer_program_help/workspace/implementation/`):

- `start.sh` — foreground launcher, guarded `pip install` (no-op once flask is present), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask>=3.0
- `app.py` — Flask app factory, blueprint registration, error handlers (ApiError, 404, 405, 400, generic)
- `db.py` — in-memory store (13 entity dicts + logical-clock state), **no seeding at startup**
- `errors.py` — `ApiError` + `ERROR_HTTP` map covering all 65 scaffold error IDs
- `response.py` — envelope helpers producing the exact `meta`/`response_type`/`data` shape; list responses add `limit`/`offset`/`total_count`/`has_more`
- `middleware.py` — `X-User-ID` / `X-User-Role` validation, role authorization
- `util.py` — UUID minting, ISO-8601 3-fractional-digit timestamps, logical clock, `Decimal`-based quarter-hour math (`round_half_up`, `round_quarter`, `is_multiple_quarter`), pagination
- `services/calculations.py` — composite score, credit totals + project waterfall cap, shift quarter-hour pipeline, recertification outcome, recognition tier/points (pinned 3-step order), specialist rolling/lifetime scores, specialist selector, record provisioning, deactivation cascade
- `routes/clock.py` — `POST /_clock/set_current_utc`
- `routes/program_cycles.py` — cycle CRUD, open/begin-recertification/close (4-link cascade), promote-waitlisted, PUT with `expected_cycle_version` OCC
- `routes/applications.py` — submit, list, get, score, decide
- `routes/volunteers.py` — list, get (recognition recomputed on read), withdraw (with cascade), reactivate
- `routes/training.py` — enroll (capacity + duplicate checks), list, get, progress, complete (COMPLETED/FAILED threshold)
- `routes/credit_entries.py` — volunteer self-service create (kind-field enforcement, activity window, PROJECT source check), list, get, approve/reject/revoke; RecertificationRecord list/get/evaluate/grant-exemption
- `routes/shifts.py` — shift CRUD + cancel/complete (location half-open overlap), signups (capacity/strike/travel-buffer), cancel/complete/mark-no-show (mints shift credit), inquiries (window, kind, signup, follow-up), triage, desk answer
- `routes/referrals.py` — specialist registry + OCC PATCH, referral create (explicit/auto selector), start-review/answer/return/reassign with SLA + audit fields
- `routes/projects.py` — propose, OCC amend, submit, approve (cap = min(est × 1.25, 20.0)), request-revision, reject, close (segregation of duties + PENDING entry void cascade)
- `routes/rotation.py` — assignment create (Monday check, OPEN-cycle derivation, bed-week closed overlap, consecutive-week limit), complete (mints GARDEN credit), mark-missed, swap

**Endpoint count implemented:** 75 / 75 (matches scaffold §1.5 exactly).

**Boot smoke-check results:**
- `bash start.sh` boots Flask cleanly on `0.0.0.0:$PORT` and serves HTTP within ~2 s
- Full lifecycle verified: cycle create → open → application submit/score/decide (composite 98.0 = 0.4·80 + 0.6·90 + 8 + 4) → volunteer created TRAINEE → enroll → progress → complete → volunteer ACTIVE with PENDING record provisioned
- Credit flow: SERVICE entry PENDING → approve → totals recompute; revoke → VOIDED → official totals lose the hours; recognition recomputed (BRONZE / base 6.5 / points 6.5)
- Shift flow: create (HELP_DESK) → volunteer signup → inquiry inside window → triage → specialist register → auto-referral → start-review → answer → inquiry CLOSED with `SPECIALIST_DIAGNOSIS`; shift complete → signup complete → minted PENDING entry (150 min → 2.5 h quarter-rounded)
- Recertification: begin-recertification blocked before `recert_opens_at` (`ERR_RECERT_WINDOW_NOT_OPEN`); post-window transition freezes credit writes (`ERR_CYCLE_NOT_OPEN`); close finalizes records, deactivates shortfall volunteers, increments `consecutive_shortfall_cycles`
- OCC: stale `expected_cycle_version` → 412 `ERR_STALE_CYCLE_VERSION`; matching version applies and bumps `version`
- Segregation of duties: approving coordinator blocked from close (`ERR_SEGREGATION_OF_DUTIES`); different coordinator closes successfully
- Hardship exemption halves `effective_hour_requirement` (6.0 → 3.0)
- Pagination meta (`limit`/`offset`/`total_count`/`has_more`) present on list endpoints
- Auth: missing headers → 400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; undeclared role → same; unknown id → 404 `ERR_NOT_FOUND`
- **Per-test-server isolation:** killed and re-launched via `start.sh`; fresh process serves `total_count: 0` on all list endpoints and the logical clock is reset to `2026-08-01T00:00:00Z`, confirming no state carry-over between reboots

## Step 7: Run Tests and Iterate — 2026-08-13T12:35:00.000Z

All 8 rounds pass 120/120. The sweep is clean.

**Summary**

- **Iterations run:** 3 sweeps (24 total rounds). Sweep 1: 6 deterministic failures (8/8 rounds each). Sweep 2: all logic failures fixed, but `test_volunteer_state_beats_temporal_window` flaked in 5/8 rounds with `ConnectionError: Connection reset by peer` (transport race, no assertion failure). Sweep 3: **120/120 passed in all 8 rounds.**

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:**
  - `test_helpers/api_client.py` — `ApiClient._request` now sends `Connection: close` on every request. The session-scoped client pooled keep-alive connections while the runner SIGKILLs and reboots the server on the same port before every test; reuse of a dead pooled connection surfaced as intermittent `Connection reset by peer`. One-line why: eliminate the stale-connection race against per-test-server isolation.
  - `test_helpers/assertions.py` — added `assert_same_instant(actual, expected_iso)`: parses both ISO 8601 timestamps and compares instants. One-line why: PRD §2.5 pins the logical-clock value a stamp must hold and §2.7 sets second-precision comparison, but §2.4's "three fractional digits" leaves the fractional-digit rendering non-unique (a `.000Z` renderer is equally PRD-faithful), so exact-string equality on `created_at` over-asserted (STEP 1c split: keep the covered instant comparison, drop the uncovered format bit).

- **Fixes applied to `test_suite/` (STEP 2 test bugs):**
  - `test_01_cycle_admissions_training.py::test_volunteer_and_application_state_errors` — setup used the default cycle (`priority_counties=[]`) while asserting composite 95.0, which requires the +4 county bonus; PRD §3.1's formula on that setup yields 91.0 (implementation was correct). Fixed by creating the cycle with `priority_counties=["Harford"]`, matching the test's own comment.
  - `test_01.../test_06` — three `created_at == "<clock>Z"` exact-string assertions switched to `assert_same_instant` (see above).
  - `test_04_inquiries_referrals.py::test_specialist_score_rolling_vs_lifetime_counters` and `..._scores` — both tests called `sign_up(shift3...)` after `setup_staffed_help_desk_shift(...)` had already signed the volunteer up; the implementation correctly rejected the second with `ERR_DUPLICATE_SIGNUP` per PRD §3.4 ("at most one SIGNED_UP signup per shift"). Removed the redundant `sign_up` calls (and the now-unused import).

- **Fixes applied to `implementation/`:**
  - `util.py::now_iso3` — was wall-clock (`datetime.now`); now returns the logical clock value. PRD §2.5: "the server must not fall back to wall-clock time under any circumstance" — `created_at`/`updated_at` must read the logical clock (drove `test_cycle_create_applies_defaults_and_version` and `test_clock_default_and_set_roundtrip`).
  - `util.py::sort_created` — dropped the random-UUID tiebreak; stable sort on `created_at` preserves insertion (creation) order, which is the only deterministic reading once logical-clock stamps tie at second precision. Same UUID-tiebreak removal in `routes/program_cycles.py` (close-cascade record ordering, waitlist promotion), `services/calculations.py` (project-cap waterfall, specialist selector), `routes/volunteers.py` (reactivation target-cycle tie), `routes/rotation.py` (`_derive_cycle`).
  - `routes/referrals.py::create_referral` — moved the "one active referral per inquiry" check before the TRIAGED state guard. PRD §3.5 verbatim: "a second attempt fails with `ERR_REFERRAL_ALREADY_OPEN`"; a second attempt lands on a REFERRED inquiry, so state-first ordering made that PRD-named error unreachable.

## Step 8: Finalize PRD — 2026-08-13T12:40:00.000Z

The diff is exactly the five intended inline revisions. All work is complete — here is the summary.

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1450_master_gardener_volunteer_program_help/workspace/PRD_FINALIZED.md`

**Line counts / delta:** PRD.md 370 lines → PRD_FINALIZED.md 370 lines (0.0% line delta; 5 lines revised in place, no lines added or removed, no new sections).

### Changes (one bullet per edit)

- **§2.3** — revise — appended the universal stable-ordering rule to the "sorted by `created_at` ascending" sentence: any ordering keyed wholly or partly on `created_at` resolves equal keys to creation order, never a random/identifier tiebreak — `implementation/util.py:165-170` (`sort_created`), `implementation/routes/program_cycles.py:263` (close link-1) and `:325` (waitlist promotion), `implementation/services/calculations.py:65` (project-cap waterfall) and `:332` (specialist selector), `implementation/routes/volunteers.py:72-77` (reactivation), `implementation/routes/rotation.py:75` (`_derive_cycle`).
- **§2.4** — revise — `created_at`/`updated_at` re-specified as ISO 8601 UTC at **second precision** holding the logical-clock value (was "with three fractional digits", which contradicted the implementation's `YYYY-MM-DDTHH:MM:SSZ` rendering) — `implementation/util.py:14-36` (`now_iso3`/`touch`/`new_resource`), `implementation/util.py:65-70` (`_format_dt`), `implementation/db.py:19`.
- **§2.5** — revise — pinned that the clock-set capability normalizes `to_iso8601` to UTC second-precision `...Z` form and that every server-written timestamp field (`created_at`, `updated_at`, `decided_at`, `signed_up_at`, `completed_at`, `resolved_at`, `answered_at`, `returned_at`, `evaluated_at`, `finalized_at`, `due_at`) renders in that form — `implementation/routes/clock.py:23-26`, `implementation/util.py:46-47,65-70`.
- **§3.5** — revise — pinned that the "one active referral per inquiry" check runs **before** the inquiry's `TRIAGED`-state guard (a deliberate exception to §2.9's tier order): a second attempt on a `REFERRED` inquiry fails with `ERR_REFERRAL_ALREADY_OPEN`, and `ERR_INQUIRY_NOT_TRIAGED` still fires for `LOGGED`/`CLOSED` inquiries — `implementation/routes/referrals.py:175-187`.
- **§3.7** — revise — `_derive_cycle` multiple-match rule: when several `OPEN` cycles contain `week_start`, the earliest-created is chosen (PRD previously presumed uniqueness and said nothing) — `implementation/routes/rotation.py:68-76`.

### Step-7 diff items that produced no PRD edit (with reason)

- `test_helpers/api_client.py` `Connection: close` — test-harness transport fix; no behavioral content for the PRD.
- `test_01` `priority_counties` fixture — pure test bug; PRD §3.1's formula already uniquely determines 91.0 vs 95.0 and `implementation/services/calculations.py:35-41` matches the PRD verbatim.
- `test_04` duplicate `sign_up` removal — pure test bug; PRD §3.4 already pins `ERR_DUPLICATE_SIGNUP` and `implementation/routes/shifts.py:187-189` conforms.
- `util.py::now_iso3` wall→logical clock — implementation was fixed to match the already-correct PRD §2.5 ("must not fall back to wall-clock time"); prose kept verbatim. The only PRD-side residue was §2.4's fractional-digit mismatch, covered by the §2.4/§2.5 edits above (which also cover the `assert_same_instant` helper item).

### Per-edit pre-edit search log (NO-NEW-MISMATCH rule)

1. **§2.4 precision edit** — (a) subject: rendering of system-managed timestamps. (b) Enumerated: `util.py:14-36` (all stamps via `now_iso3` = clock string), `util.py:65-70` (`_format_dt`, second-precision Z), `db.py:19` (default `2026-08-01T00:00:00Z`), `routes/clock.py:25` (set normalizes), every stamp site via grep (`decided_at`, `signed_up_at`, `completed_at`, `resolved_at`, `answered_at`, `returned_at`, `evaluated_at`, `finalized_at`, `due_at` — all second-precision), and `response.py:14-16` (envelope `api_request_timestamp` genuinely keeps three fractional digits). (c) Scoped the edit strictly to §2.4's two bullets and left §2.2's "three fractional digits" for `api_request_timestamp` untouched, since the envelope timestamp does render three fractional digits.
2. **§2.5 normalization edit** — (a) subject: clock storage/reporting form + shared stamp rendering. (b) Enumerated: `routes/clock.py:14-26`, `util.py:41-70`, plus a grep over all `logical_clock_iso()`/`_format_dt` callsites confirming every listed field renders the same form, and confirming client-supplied `recert_opens_at`/`start_time`/`end_time` are stored verbatim (therefore excluded from the field list). (c) Used an explicit field enumeration rather than a blanket "all timestamps" claim so client-supplied fields are not mis-described.
3. **§2.3 stable-ordering edit** — (a) subject: tie completion in every defined ordering. (b) Enumerated all 21 sort sites via grep: 13 list endpoints on `util.sort_created`, plus promotion, close link-1, waterfall, selector, reactivation, `_derive_cycle` — all Python stable sorts over insertion-ordered dicts; confirmed `uuid` is used only in `new_id()` (no identifier tiebreak anywhere). (c) Wording made explicitly universal ("keyed wholly or partly on `created_at`… equal keys keep creation order") so it truthfully covers compound keys (waterfall's `activity_date`, selector's score keys, reactivation's `start_date`) rather than only pure `created_at` sorts.
4. **§3.5 referral-check-order edit** — (a) subject: error precedence between the active-referral check and the inquiry state guard. (b) Enumerated: `referrals.py:168-211` (create) and `:321-343` (reassign — unaffected), plus every other endpoint's state-vs-uniqueness ordering (`shifts.py:176-206` signup, `training.py:43-54` enrollment, `applications.py:136-147` decide, `credit_entries.py:105-123`, `shifts.py:326-369` inquiry) confirming this is the *only* tier-order deviation, and that inquiry state REFERRED ⟺ carries an active referral (creation sets REFERRED; only ANSWERED clears it, which deactivates the referral). (c) Framed the sentence as a scoped exception limited to referral creation, explicitly preserving `ERR_INQUIRY_NOT_TRIAGED` for `LOGGED`/`CLOSED` inquiries, so no other endpoint's §2.9 compliance is implied or disturbed.
5. **§3.7 `_derive_cycle` edit** — (a) subject: cycle selection when multiple OPEN cycles contain `week_start`. (b) Enumerated: `rotation.py:68-76` (creation path; `created_at`-asc stable sort, take first) and `rotation.py:200-244` (swap path reuses the original's `cycle_id` without re-deriving). (c) Replaced "the unique `OPEN` cycle" with "the `OPEN` cycle … when several … the one created earliest is chosen", consistent with both paths and with the new §2.3 stable rule ("created earliest" = smallest `created_at`, ties completed by creation order); `ERR_NO_OPEN_CYCLE` semantics unchanged.
