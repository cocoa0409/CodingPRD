# Worklog — task_1799_school_volunteer_screening_placement

## Step 1: Create Task Directory — 2026-08-14T17:17:00.000Z

Task directory `tasks/task_1799_school_volunteer_screening_placement/` and `workspace/` were pre-created and pre-assigned by the invoking command. Step 1 treated as DONE per instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-14T17:58:30.000Z

All three scaffold artifacts are generated and lint-clean. Summary:

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1799_school_volunteer_screening_placement/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`, 18 instances (2 per each of the 9 Difficulty Rules)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`, 23 active corner instances + 15 `excluded_because` stubs pointing at §1.8 instances

**Design highlights**
- Archetype: compliance/audit + access-control-matrix; flat entity topology (11 peer entities linked by FK fields, reverse-reachability via filtered-list GETs); cyclic state machines; hierarchical-override role model (DistrictCoordinator ⊃ CampusAdmin, plus entity-backed Volunteer).
- Entities: Campus, Volunteer, BackgroundCheck, TrainingModule, TrainingRecord, Opportunity, Placement, HourEntry, VisitCheckIn, IncidentReport, RecognitionAward; 44 endpoints including `POST /_clock/set_current_utc` with the mandatory `2026-08-01T00:00:00Z` startup default driving the expiry sweep.
- Difficulty mechanics: dual-variant hour totals (verified vs provisional) and opportunity fill (committed vs projected); combinatorial rules in two modes (screening decision matrix = mode a; per-entry-round-then-sum recognition points = mode b, pinned 3.8+1.3=5.1 vs 5.0); cyclic Volunteer re-screening loop (ENHANCED 365d / BASIC 730d); two transitive cascades (incident HIGH → suspend → placement cancel → opportunity recount; hour verify → totals → tier → auto-award); priority conflicts (state>safety on confirm, referential>temporal on hour logging); boundary checks (capacity `>=` at exactly full; tier `>=` at exactly 50.0h); two overlap semantics (half-open placement windows vs buffered closed check-in window + singleton session); two compensating invariants (seat conservation confirm/cancel; hours/points conservation verify/revoke); two OCC rules on `Volunteer.version` (412 `ERR_STALE_VERSION`), with all `expected_volunteer_version` payloads using `${var}` captures.

**Verification**: `scaffold_lint.py` verdict pasted verbatim —
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(44 endpoints, 11 entities, 18 §1.8 + 38 §1.9 active instances, 604 calls scanned). Fixes applied during iteration: quoted bracket/brace grounds refs for YAML flow-sequence safety, added `placement_id?` to `GET /incident-reports` for FK reverse-reachability, retired unreachable `ERR_CLEARANCE_EXPIRED` (expiry enforced via sweep demotion), added `ACTIVE/RESCREEN_REQUIRED/CLEARANCE_GRANTED → REMOVED` transitions so SUBSTANTIATED adjudication of LOW/MEDIUM incidents has a defined path, and corrected the duplicate-award corner to reflect that a failed duplicate does not consume the OCC version.

## Step 3: Copy Shared Files — 2026-08-14T17:59:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1799_school_volunteer_screening_placement/workspace/INSTRUCTION.md` (verified present in workspace/).

## Step 4: Generate PRD — 2026-08-14T18:16:00.000Z

PRD generation complete. Output written to `/home/ubuntu/github/CodingPRD/tasks/task_1799_school_volunteer_screening_placement/workspace/PRD.md` (290 lines, ~30 KB), generated solely from the skill spec and `SCAFFOLD.yaml` — the two difficulty/corner design files were never opened.

**Document structure** (domain-derived, not template-copied):
- §1 Introduction (2 paragraphs, business-context angle)
- §2 nine subsections: RBAC with per-role identity prose (opaque `DistrictCoordinator`/`CampusAdmin`, entity-backed `Volunteer`) · verbatim §2.2 response envelope (verified byte-identical to `section-2.2-response-structure.md`) · pagination · common resource properties + derived-field reconciliation (names the four `common_fields: false` entities as carrying only `id`/`created_at`) · logical clock + three-part sweep · clearance levels & screening decision matrix · ten-stage ordered validation pipeline · OCC · numeric precision
- §3 seven lifecycle subsections: district configuration · intake & screening · re-screening cycle · opportunities & placements · check-in & badges · hours & recognition · incidents/suspension/removal — zero endpoint paths, state-pair framing throughout
- §4 endpoint table: 44 rows, exactly 4 columns · §5 error catalogue: 32 rows, exactly 2 columns

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + endpoint inputs/outputs + query/path params: 72 required, 72 present, 0 missing
- (all 32 error IDs and all 59 state/enum values also present in backticks)
Status: PASS

Rule coverage check:
- validations[] priority ordering: 10 stages checked, 10 expressed as an explicit ordered first-failure pipeline (incl. stage-5 internal order and stage-7 endpoint order), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write operation + expected_volunteer_version + ERR_STALE_VERSION/HTTP 412 named; no race framing), 0 missing
- state_machines[].transitions: 41 checked (Volunteer 21, BackgroundCheck 5, Opportunity 4, Placement 4, HourEntry 3, VisitCheckIn 2, IncidentReport 2), 41 fully expressed with preconditions and side effects, 0 missing
- calculations[]: 9 checked, 9 fully expressed in precise prose (rank mapping, decision matrix incl. inadequate-level stay-branch, 730/365-day validity with tie-break selection, dual hour totals, pinned round-first-then-sum points with the 3.8+1.3=5.1 worked example, inclusive tier thresholds 20/50/100, fill-count variants, strict-greater training compliance, per-campus-per-day badge sequence), 0 missing
- validations[] conditions: all matched to their error_id in §2.7/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (DENIED/REMOVED cascades, SYSTEM_SUSPENSION vs SYSTEM_REMOVAL asymmetry, SYSTEM_RESTRICTION self-loop, sweep counters, match response fields), 0 missing
- entities[].fields[] structured content: defaults (empty string/null/zero/empty array) and constraints reconstructible from prose, 0 missing
- sibling-branch symmetry: adjudication/reinstatement/cancel/sweep sibling groups rendered with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 458
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: no pseudocode operators (`==`, `>=`, `+=`, …) anywhere, no fuzzy/approximating words, §2.2 byte-identical to the canonical block (verified via diff), and the file ends at §5 with no audit footer.

## Step 6: Generate Implementation — 2026-08-14T18:25:00.000Z

(completed before Step 5; Steps 5 and 6 were launched concurrently)

Fresh boot via `start.sh` works and the error envelope is correct. The implementation is complete.

Generated a complete Python + Flask implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1799_school_volunteer_screening_placement/workspace/implementation/` for the School Volunteer Screening & Placement benchmark task.

**File layout:**
- `start.sh` — foreground launcher, guards `pip install` behind an import check (critical for per-test-server reboots), `exec python3 app.py`
- `requirements.txt` — flask>=3.0.0
- `app.py` — Flask entry, error handlers (APIError → envelope, 404/405, generic), route registration, `0.0.0.0:$PORT` (default 10000)
- `clock.py` — logical clock, startup default exactly `2026-08-01T00:00:00Z`, ISO8601 3-fractional-digit serialization
- `db.py` — empty in-memory stores, no seeding
- `errors.py` — all 33 error IDs from the scaffold catalog with correct HTTP statuses
- `response.py` — envelope `{meta:{api_request_id, api_request_timestamp, ...pagination}, response_type, data}`; error envelope `{meta, response_type:"error", data:{error_id, message}}`
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (p1), role-list + Volunteer ownership (p2)
- `pagination.py` — `limit`/`offset` (default 10, min 1, max 100, offset 0), `total_count`, `has_more`, sort by `created_at` ASC
- `services.py` — all calculations: level rank adequacy, screening decision matrix (NONE/MINOR/DISQUALIFYING → CLEARED/CLEARED_WITH_FLAGS/DENIED, flags sorted), clearance validity (BASIC 730d / ENHANCED 365d, max decided_at tie-break created_at DESC), volunteer hours (2dp half-up), recognition points (per-entry 1dp half-up then exact sum), tier thresholds (20/50/100 inclusive), opportunity fill counts, training compliance, badge codes (per campus per UTC day, 4-pad), all cascades (removal/suspension/restriction)
- `routes/` — 11 modules covering every endpoint in §1.5 including `POST /_clock/set_current_utc` with the three-part sweep and `POST /opportunities/{id}/match` selector

**Key behaviors verified via live smoke tests:** intake → check → adjudicate → CLEARANCE_GRANTED/ACTIVE branching by training compliance → opportunity publish → placement request/confirm with full gate stack → badge issuance (`LNC-0001`) → hour logging with per-entry rounding (2.5h TUTORING → 3.8 pts) → verify cascade → clock sweep expiring checks and demoting ACTIVE→RESCREEN_REQUIRED → HIGH incident auto-suspension with prior_status capture → UNFOUNDED reinstatement. Validation pipeline ordering (auth → existence → state → safety gates → referential → temporal → constraint → OCC → shape) is enforced per PRD §2.7.

## Step 5: Generate Unit Tests — 2026-08-14T18:46:00.000Z

All audits pass. The work is complete.

**Generated test infrastructure** in `/home/ubuntu/github/CodingPRD/tasks/task_1799_school_volunteer_screening_placement/`:

**`test_helpers/` (9 files)** — `types.py` (8 status/enum sets + 11 entity TypedDicts with correct `common_fields` branching: append-only Campus/TrainingModule/TrainingRecord/RecognitionAward omit `updated_at`/`version`), `api_client.py` (41 endpoint methods covering the full PRD §4 map), `api_errors.py` (all 32 error IDs with HTTP statuses, registered via `set_error_http_status_map`), `assertions.py` (11 entity assertions + `assert_clock_instant` which compares logical-clock instants on whole-second prefixes to tolerate `.000Z`/`Z`/`+00:00` serialization variants), `factories.py`, `constants.py` (730/365-day validity, 20/50/100 tier rungs, point multipliers, 12-hour cap, 30-minute check-in buffer), `test_users.py` (opaque DC/CampusAdmin shared headers + mandatory `make_volunteer_headers` builder for the entity-backed Volunteer role), `fixtures.py` (composite lifecycle builders: active/flagged/clearance-granted volunteers, confirmed placements, hour logging/verification, check-ins, incidents, OCC-aware check initiation), barrel `__init__.py`.

**`test_suite/` (conftest + 9 files, 73 tests)** — all 73 docstrings carry grep-verified verbatim PRD citations plus exactly one terminal `Design:` line resolving to a real instance.

**Coverage audit results**
- Queue A: all 18 difficulty instances have exactly 2 tagged tests (36).
- Queue B: 37 of 38 non-stub corner instances translated; all 16 `excluded_because:` stubs left untranslated with cross-references verified resolvable.
- **1 instance skipped per the PRD-first filter**: `Corner/entities/volunteer_computed_field_input_ignored` — no PRD sentence states that client-supplied computed/system fields in a create payload are ignored; strict-schema vs lenient handling is an open design space, so the asserted outcome is not uniquely derivable. Gap left as a gap.

**Key adjudication call**: `Difficulty/priority_pair_validation_conflict/hour_entry_referential_beats_temporal`'s recipe asserts `ERR_PLACEMENT_VOLUNTEER_MISMATCH` on `POST /hour-entries` by another volunteer — but the PRD uniquely derives `ERR_FORBIDDEN` there (§2.1 lists hour-logging among Volunteer-ownership operations, and §2.7's ordered pipeline runs ownership at stage 2, before stage 6). The instance's underlying rule (referential p6 beats temporal p7) is PRD-covered and reachable via the sibling `POST /check-ins` pathway named in the same validation, so both of this instance's tests use placement-linked check-ins with a foreign placement plus an out-of-window timestamp (one before the window, one after), asserting `ERR_PLACEMENT_VOLUNTEER_MISMATCH`.

**Verification run**: `py_compile` clean on all files, pyflakes clean on the suite, `test_helpers` imports successfully, coverage audit and verbatim-citation audit both pass.

## Step 7: Run Tests and Iterate — 2026-08-14T19:05:00.000Z

Clean 8-round sweep achieved. Final summary:

**Iterations run:** 2 (initial sweep: 70/73 × 8 rounds, 3 deterministic failures identical across all rounds; post-fix sweep: 73/73 × 8 rounds, union of failures empty).

**Tests deleted:** none.

**Fixes applied to `test_suite/`:**

1. `test_suite/test_01_volunteer_intake_and_screening.py` — `test_duplicate_pending_check_rejected`: the setup initiated the first check from `APPLIED`, leaving the volunteer `UNDER_SCREENING`; per PRD §2.7's ordered pipeline the stage-4 state gate (`ERR_VOLUNTEER_INVALID_STATE` — initiation permitted only from `APPLIED`/`ACTIVE`/`RESCREEN_REQUIRED`) pre-empts the stage-8 `ERR_CHECK_ALREADY_PENDING` rule in that state, so the asserted error contradicted the PRD for that setup. Reworked the setup to walk the volunteer to `ACTIVE` and open a proactive re-screen check (PRD §3.3 explicitly permits initiation while `ACTIVE`) — the only posture where stage 4 passes and `ERR_CHECK_ALREADY_PENDING` is the uniquely determined outcome (and still demonstrates the corner's p8-beats-p9 point with a current OCC version). The list assertion was adjusted from `total_count == 1` to `== 2` to match the new (adjudicated + pending) check history.

2. `test_suite/test_03_opportunities_and_matching.py` — `test_projected_count_includes_requested_before_confirmation`: `KeyError: 'id'` because the test dereferenced `recruited["id"]` on the composite dict returned by the `create_active_volunteer` fixture; fixed to `recruited["volunteer"]["id"]`.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:**

3. `workspace/implementation/services.py` — added `latest_cleared_check(volunteer)` (latest `decided_at` among `CLEARED`/`CLEARED_WITH_FLAGS`, tie-break later `created_at`), backing the PRD §2.6 rule "the volunteer's latest cleared check level must be adequate for the level implied by the opportunity's `required_contact_type`".

4. `workspace/implementation/routes/placements.py` — `confirm()`: the stage-5 adequacy gate previously reused `adequate_cleared_checks(vol)`, which filters against the *volunteer's own* `required_check_level`, so a BASIC-cleared SUPERVISED volunteer could confirm onto an UNSUPERVISED-contact opportunity (test: `test_insufficient_clearance_level_rejected`). Now compares the latest cleared check's level against the *opportunity's* implied required level via `REQUIRED_LEVEL_FOR_CONTACT`, and the stray expiry re-check was removed per the §2.7 note that expiry is deliberately not a stage-five gate.

5. `workspace/implementation/routes/opportunities.py` — `match()`: same adequacy bug in the selector's eligibility pool (checked against the volunteer's own level plus a `clearance_expires_at` proxy); replaced with the latest-cleared-check vs. opportunity-implied-level filter per PRD §3.4/§2.6.

**Key finding for generators:** the scaffold corner `duplicate_pending_check_rejected` prescribes a setup (UNDER_SCREENING + PENDING check) in which the PRD's own stage-4-before-stage-8 ordering makes the corner's asserted `ERR_CHECK_ALREADY_PENDING` unreachable — unit-test-generator should route that corner through the `ACTIVE` re-screen posture, and doc-generator may want §3.2 to spell out that a volunteer holding a PENDING check is typically `UNDER_SCREENING`, so the pending-uniqueness rejection is reachable mainly from `ACTIVE` re-screening.

## Step 8: Finalize PRD — 2026-08-14T19:12:00.000Z

Both edits are in place; the diff shows exactly the two intended changes and nothing else.

**File:** `workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md = 290 lines, PRD_FINALIZED.md = 290 lines — 0.0% line delta (both edits are within-paragraph expansions; ~+640 chars total).

### Changes (2 edits, both tracing to Step 7 implementation fixes #3/#4/#5)

- **§2.6 (Clearance Levels and the Screening Decision Matrix) — revise** — appended a defining sentence for the previously undefined term "latest cleared check" used by the opportunity-gating rule: candidate set is all of the volunteer's checks in `CLEARED`/`CLEARED_WITH_FLAGS` regardless of level (no adequacy pre-filter, unlike the expiry selector), excluding checks since moved to `EXPIRED`; selection by latest `decided_at` with ties broken toward the later-created check; no such check means the gate cannot be passed — `implementation/services.py:62-80` (`latest_cleared_check`, added in Step 7 fix #3).
- **§3.4 (Confirmation paragraph) — revise** — the confirm-time first screening gate now reads "the volunteer's latest cleared check level (§2.6) adequate for the level implied by the opportunity's `required_contact_type`" instead of the vague "clearance level adequate for the opportunity's `required_contact_type`", aligning confirmation with the selector's already-correct wording and the post-fix implementation — `implementation/routes/placements.py:136-145` (fix #4), `implementation/routes/opportunities.py:157-170` (fix #5).

### Step 7 items requiring no PRD edit

- **test_01 fix (`test_duplicate_pending_check_rejected`)** — test-side setup bug. PRD §2.7 already pins the ordered pipeline (stage 4 `ERR_VOLUNTEER_INVALID_STATE` before stage 8 `ERR_CHECK_ALREADY_PENDING` before stage 9 OCC), §3.2 already pins initiation permitted only from `APPLIED`/`ACTIVE`/`RESCREEN_REQUIRED`, and §3.3 already pins proactive re-screening while `ACTIVE`. Implementation `routes/background_checks.py:36-57` matches the PRD verbatim. Prose kept unchanged.
- **test_03 fix (`KeyError: 'id'`)** — pure fixture bug (composite dict dereference); no PRD behavior involved.

### Per-edit pre-edit search log

**Edit 1 (§2.6 "latest cleared check" definition):**
- (a) Subject: the definition/semantics of the "latest cleared check" selector used by opportunity gating.
- (b) Paths enumerated via `grep -rn "latest_cleared_check|adequate_cleared_checks|clearance_expires_at|level_adequate|REQUIRED_LEVEL_FOR_CONTACT"` over all `implementation/**/*.py`, each read: `services.py:25` (contact→level map), `services.py:33-34` (`level_adequate`), `services.py:47-59` (`adequate_cleared_checks` — the *different*, adequacy-pre-filtered expiry selector), `services.py:62-80` (`latest_cleared_check`), `services.py:83-101` (`recompute_clearance_expires_at`), `services.py:327-353` (adjudication adequacy vs the volunteer's own `required_check_level`), `routes/placements.py:136-153` (confirm gates), `routes/opportunities.py:157-199` (match pool), `routes/clock_routes.py:41-49` (sweep), `routes/incidents.py:134` (reinstatement), plus a sweep of `check_ins.py`/`hour_entries.py`/`training.py`/`awards.py` confirming no other clearance-level gating exists (check-ins gate only on `ACTIVE`).
- (c) Wording adjustments: scoped the sentence with "For this gate" and "regardless of level" so it cannot be misread as redefining the separate adequate-set expiry selector pinned in §2.6's final paragraph (which `recompute_clearance_expires_at` implements); made the `EXPIRED` exclusion explicit since the clock sweep moves checks out of the candidate statuses; added the empty-set case because both call sites treat `None` as gate failure.

**Edit 2 (§3.4 confirmation gate wording):**
- (a) Subject: which check's level is compared at confirmation's stage-5 adequacy gate.
- (b) Paths enumerated: `routes/placements.py:135-153` (confirm gate stack, post-fix), `routes/opportunities.py:161-176` (match pool — the parallel endpoint already described in PRD with "latest cleared check"), `services.py:62-80` (selector definition), and PRD-side §2.7 stage 5 (line 105) which names the gate generically without specifying the check.
- (c) Wording adjustments: reused the exact defined term "latest cleared check level" with a `(§2.6)` cross-reference rather than re-stating the definition inline, keeping §2.7 stage 5 verbatim (it is a summary that delegates the rule's content to §2.6, so no competing specification remains).

## Step 9: Complete PRD — 2026-08-14T19:20:00.000Z

The diff is complete and minimal. All work is done.

**Source vs output**: `PRD_FINALIZED.md` (290 lines / 55,330 chars) → `PRD_COMPLETED.md` (292 lines / 58,251 chars), char-delta **+2,921**. File: `workspace/PRD_COMPLETED.md`

**Counts**: 15 ambiguity-pins, 1 mismatch-revision (16 changes total, all inline inserts/revisions; no new sections).

**Changes** (one bullet each):

- §2.1 — revise — mismatch — the exhaustive-sounding ownership-enforcement list omitted two operations the impl enforces with `ERR_FORBIDDEN`: check-in creation (payload `volunteer_id`, when supplied) and reading a check-in; both added to the list — `implementation/routes/check_ins.py:29-35,142-143`, `implementation/middleware.py:36-39`
- §2.2 — insert — ambiguity — undeclared paths and unsupported methods on declared paths are rejected with `ERR_NOT_FOUND` (HTTP 404) in the standard error envelope — `implementation/app.py:34-40`
- §2.3 — insert — ambiguity — pinned: non-integer/out-of-range `limit` or `offset` (incl. negative offset) → `ERR_INVALID_REQUEST`; `created_at` sort ties broken by `id` ascending; `has_more` true exactly when `offset` + items-on-page < `total_count` — `implementation/pagination.py:11-44`
- §2.4 — insert — ambiguity — `version` starts at 1 at creation with `updated_at` initially equal to `created_at`; client-supplied datetimes (opportunity `starts_at`/`ends_at`, training-record `completed_at`) are stored normalized to UTC three-fractional-digit form, not echoed verbatim — `implementation/routes/volunteers.py:17-21`, `implementation/routes/opportunities.py:71-72`, `implementation/routes/training.py:97-104`
- §2.5 — revise — ambiguity — "advances the logical clock" → sets it to any well-formed ISO 8601 instant; no monotonicity requirement (backward sets accepted) — `implementation/routes/clock_routes.py:18-26`
- §2.5 — revise — ambiguity — "each affected volunteer's version incremented" → only demoted volunteers bump `version`; an `ACTIVE` volunteer whose recomputed clearance remains valid is otherwise untouched — `implementation/routes/clock_routes.py:48-56`
- §2.7 stage 10 — insert — ambiguity — a missing or unparseable JSON body is evaluated as an empty object — all routes use `request.get_json(silent=True) or {}` (e.g. `implementation/routes/volunteers.py:42`)
- §2.8 — insert — ambiguity — OCC value is integer-coerced for comparison; non-coercible values are ignored (not treated as stale); absent/null fails stage ten with `ERR_INVALID_REQUEST` — `implementation/routes/background_checks.py:49-66`, `implementation/routes/awards.py:46-63`
- §3.2 — insert — ambiguity — a non-denied adjudication landing while the volunteer is outside the three named branches (e.g. `SUSPENDED` via an intervening HIGH incident) records the decision on the check and bumps the volunteer's `version`, but leaves status/flags/clearance unchanged — `implementation/services.py:355-356`
- §3.4 — insert — ambiguity — `max_placements`, when supplied, must be a non-negative integer else `ERR_INVALID_REQUEST` — `implementation/routes/opportunities.py:152-155`
- §3.4 — insert — ambiguity — match ranking's remaining ties (equal hours and equal `created_at`, common under the logical clock) break by volunteer `id` ascending — `implementation/routes/opportunities.py:202`
- §3.4 — insert — ambiguity — the selector increments the opportunity's `version` on every call, including an empty match creating nothing — `implementation/routes/opportunities.py:231-232`
- §3.5 — revise — ambiguity — "forced to the caller's identity" → forced to the caller's own identity *and supplying someone else's id is an ownership violation* (403, not silent overwrite) — `implementation/routes/check_ins.py:29-35`
- §3.6 — revise — ambiguity — auto-award on tier raise covers *every newly reached rung* (above old, at or below new), skipping tiers already awarded; auto awards carry an empty `note` — `implementation/services.py:148-170`
- §3.7 — insert — ambiguity — UNFOUNDED reinstatement with `prior_status` = `RESCREEN_REQUIRED` returns the volunteer to `RESCREEN_REQUIRED` — `implementation/routes/incidents.py:141-142`
- §3.7 — insert — ambiguity — SUBSTANTIATED against a volunteer already `DENIED`/`REMOVED` leaves the volunteer record unchanged and runs no cascade; the report still resolves — `implementation/routes/incidents.py:121-128`

**Notable non-changes** (verified already uniquely pinned by the PRD): the full §2.7 pipeline ordering as implemented in every route; badge-code count-based sequencing (the PRD's "equal timestamps ordered by created_at" phrase is vacuous under the count-based scheme, which yields identical results since check-ins are never deleted); the ACTIVE re-screening self-loop overwriting flags unconditionally (matches §3.2's unconditional "overwriting" language); and check-initiation "first check" ≡ `APPLIED` status equivalence.
