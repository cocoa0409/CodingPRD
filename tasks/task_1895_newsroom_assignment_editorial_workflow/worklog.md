# Worklog — task_1895_newsroom_assignment_editorial_workflow

## Step 1: Create Task Directory — 2026-08-14T23:25:00.000Z

Directory `tasks/task_1895_newsroom_assignment_editorial_workflow/` and `workspace/` created by pipeline launcher (pre-existing; orchestrator instructed to start at Step 2).

## Step 2: Generate Scaffold — 2026-08-15T00:19:00.000Z

Scaffold generation complete. All three artifacts are written to `/home/ubuntu/github/CodingPRD/tasks/task_1895_newsroom_assignment_editorial_workflow/` and pass `scaffold_lint.py` with a clean verdict (pasted verbatim below). No sibling task directories were read at any point.

**Final lint verdict (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    60
  §1.1 entities declared:     10
  §1.8 instances scanned:     18
  §1.9 instances scanned:     57
  Calls scanned (§1.8+§1.9):  1072

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files:**
- `SCAFFOLD.yaml` (962 lines) — §1.0–§1.7 only: 10 entities (StaffMember, Pitch, Story, Assignment, PublicationSlot, ReviewRecord, Correction, AnalyticsReport, BreakingNewsEvent, StaffCallIn), 8 state machines, 2 OCC concurrency rules on `Story.version`, 8 calculation rules, 13 ordered validation rows, 60 endpoints, 29 error codes, 9 roles (8 entity-backed + NewsDirector opaque to solve empty-DB bootstrap).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (748 lines) — single `scaffold_difficulty_design:` key; all 9 rule_ids × 2 instances = 18, every numeric assert pre-computed (e.g. priority 22.00/13.20/54.00/108.00, payroll 9076 vs forbidden 9075, SETTLED 390.00 vs REALTIME 351.00).
- `SCAFFOLD_CORNER_DESIGN.yaml` (1504 lines) — single `scaffold_corner_design:` key; 64 instances (57 active + 7 `excluded_because:` stubs) across all 9 taxonomy sections.

**Design highlights (harder-than-expert targeting):**
- **Cascades**: breaking-event activation drives a 3-hop chain (assignment BUMPED → story ON_HOLD → slot release); RETRACTION issuance drives a 2-hop chain (story RETRACTED → analytics VOID).
- **Precedence**: OCC pinned as its own validation priority (7, 412) ahead of state checks (8); dual-failure recipes pin state-beats-constraint and temporal-beats-fiscal pairings.
- **Formula chains**: priority score (multi-factor clamp, mode a), payroll (per-assignment-then-sum rounding pinned, mode b), performance score (raw→tier→multiplier order pinned to break circularity, mode c).
- **Concurrency races**: schedule and review-submit are OCC-guarded with create-with-supersede semantics, both deterministically testable via sequential calls.
- **Interval semantics**: half-open adjacency-allowed overlaps on staff vs inclusive 30-minute-buffer conflicts on slot channels.
- **Selector policy**: call-in paging with explicit eligibility/ranking (active_assignment_count ASC, created_at ASC tie-break)/empty-pool fallback.

**Two issues found and fixed during the build**: the lint's FK reverse-reachability check requires the literal `{id}` placeholder in parent path templates (renamed all path placeholders accordingly), and one stray "simultaneously" in a field description was reworded to satisfy the forbidden-vocabulary rule.

## Step 3: Copy Shared Files — 2026-08-15T00:20:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1895_newsroom_assignment_editorial_workflow/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T00:30:00.000Z

The PRD has been generated and all three hard contracts verified. Summary below.

## Deliverable

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1895_newsroom_assignment_editorial_workflow/workspace/PRD.md`

**Structure** (domain-derived, no template copying):
- §1 Introduction — 2 paragraphs (business context + accountability goals; `/newsroom` mount)
- §2 Global Specifications — 11 subsections: RBAC with per-role identity translation (8 entity-backed roles + opaque `NewsDirector`), verbatim §2.2 envelope, pagination, the logical clock (startup default `2026-08-01T00:00:00Z`, `to_iso8601`/`current_utc`), common resource properties (explicitly noting `ReviewRecord`/`AnalyticsReport` carry only `id`+`created_at`), left-to-right nested resolution, the 14-step ordered validation pipeline, OCC on story versions, segregation of duties, precision/payroll-week rules, and the three compensating counters
- §3 Business Logic — 8 subsections (staff roster, pitch/desk-review cycle, assignments & costing, editorial pipeline, slots & publication, corrections/retraction, analytics & track record, breaking news & call-ins); zero endpoint paths, all rules scattered with error IDs at their trigger points
- §4 Endpoint table — 60 endpoints, 4 columns only
- §5 Error catalogue — 29 errors, 2 columns only

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 72 required, 72 present, 0 missing
- endpoints[].request_body: 39 required, 39 present, 0 missing
- endpoints[].query_params: 15 required, 15 present, 0 missing
- path_params: 1 required, 1 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 14 checked, 14 expressed in ordered §2.7 prose (incl. OCC-before-from-state at step 7), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (schedule + reviews; expected_story_version + ERR_STALE_VERSION/412 named), 0 missing
- state_machines[].transitions: 30 checked, 30 fully expressed (incl. bubble-up ON_HOLD→DRAFT, PATCH version-bump note, 3 expiry triggers), 0 missing
- calculations[]: 8 checked, 8 fully expressed in reconstructible prose (priority score 10/25/40 ×2 + desk 5/4/3/2 + 72h/30pt clamp; 0.6/0.4 blend; 2400-min/1.5x overtime chronological allocation; round-per-assignment-then-sum payroll; 6/4/100 raw → tier 100/40 → 1.25/1.0/0.8 ×0.9 dampen), 0 missing
- validations[] conditions: 14 checked, 14 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (greenlight story spawn, kill cascade, 2-hop retraction, 3-hop bump, call-in selector ranking, is_current flip, retroactive week re-allocation), 0 missing
- entities[].fields[] structured content: all defaults/nullability/computed semantics reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (PASS/FAIL × FACT_CHECK/LEGAL, withdraw from 2 states, cancel from 2 states, MINOR/MAJOR vs RETRACTION, DESK vs ANALYTICS variants, PROVISIONAL vs FINAL cost), all symmetric, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 487
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 block is byte-identical to `section-2.2-response-structure.md`; all 29 error IDs appear in §2/§3 prose (not just §5); all state strings from all 7 state machines appear verbatim. The forbidden `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened.

## Step 6: Generate Implementation — 2026-08-15T00:50:00.000Z

The implementation is complete and verified. Here is the summary.

## What was built

A complete Python + Flask implementation of the Newsroom Editorial Workflow API at `/home/ubuntu/github/CodingPRD/tasks/task_1895_newsroom_assignment_editorial_workflow/workspace/implementation/`:

```
implementation/
├── start.sh                  # Foreground launcher; guarded pip install; exec python3 app.py
├── requirements.txt          # flask
├── app.py                    # Entry point, error handlers, blueprint registration, 0.0.0.0:$PORT
└── server/
    ├── blueprint.py          # Shared Flask blueprint
    ├── store.py              # In-memory store + logical clock (starts 2026-08-01T00:00:00Z, never wall clock)
    ├── errors.py             # ApiError carrying scaffold error_ids
    ├── envelope.py           # meta/response_type/data envelope; pagination fields limit/offset/total_count/has_more
    ├── auth.py               # X-User-ID/X-User-Role auth; entity-backed roles resolve StaffMember; NewsDirector opaque
    ├── util.py               # ISO8601 3-fractional-digit timestamps, body/pagination helpers
    ├── calc.py               # story_priority_score (DESK_FORWARD/ANALYTICS_BLEND), author_track_record,
    │                         #   assignment_cost (PROVISIONAL + weekly-OT FINAL w/ retroactive re-allocation),
    │                         #   performance_score (raw→tier→multiplier; REALTIME 0.9 dampen), live counters
    ├── serialize.py          # Public serializers; ReviewRecord/AnalyticsReport expose only id+created_at
    ├── routes_staff.py       # Staff CRUD + payroll + reverse collections
    ├── routes_pitches.py     # Pitch intake, desk-review cycle, greenlight spawns Story
    ├── routes_stories.py     # Pipeline (submit/complete-edit, OCC-pinned reviews, schedule/unschedule,
    │                         #   reopen, kill cascade, supersede, priority-score), corrections/analytics ingestion
    ├── routes_assignments.py # Propose/accept/decline/complete/cancel with overlap, cap, bubble-up
    ├── routes_slots.py       # Slots with same-channel &gt;30-minute gap rule, cancel-if-empty
    ├── routes_corrections.py # Approve/reject/issue with SoD, correction_number sequencing, RETRACTION cascade
    ├── routes_breaking.py    # Event declare/activate (3-hop bump cascade + ranked call-in fan-out)/resolve, call-in answers
    └── routes_ops.py         # POST /newsroom/ops/run-publication-scheduler, POST /_clock/set_current_utc
```

## Key spec-fidelity points implemented

- **Validation priority order** per PRD §2.7: auth (401) → role (403) → body schema (400) → path 404s left-to-right → body FK 404s → ownership (403) → OCC `ERR_STALE_VERSION` (412, before from-state) → state (409) → SoD (422) → staffing gate → referential/temporal/constraint/capacity errors with the exact error IDs and statuses from the catalog.
- **OCC** on exactly two writes (`schedule`, `reviews`) via `expected_story_version`, evaluated before state checks.
- **Calculations** with `Decimal` ROUND_HALF_UP: desk-forward priority stored at greenlight; ANALYTICS blend recomputed on read; payroll week `[Mon 00:00Z, next Mon)` with chronological 2400-minute OT threshold and per-assignment rounding before summation (retroactive re-allocation on every completion); three-stage performance scoring with REALTIME dampening.
- **Cascades**: kill (assignments → CANCELLED, slot release), breaking-event activation (bump → story ON_HOLD → slot release; independent ranked call-in fan-out by `active_assignment_count` ASC then `created_at` ASC), retraction (story → RETRACTED, analytics → VOID), call-in expiry (checkpoint, resolve, lazy on late answer).
- **Fresh-boot contract**: in-memory store starts empty (no seeding), logical clock fixed at `2026-08-01T00:00:00Z`, `start.sh` guards the pip install so per-test reboots skip it, `exec` hands off in the foreground on `0.0.0.0:$PORT`.

## Verification

Four smoke suites (written against the running server) all pass, covering: full pitch→story→review→schedule→publish pipeline; payroll overtime with retroactive re-allocation and per-assignment rounding; assignment cap/overlap/half-open-interval boundaries; review FAIL loops with round/`is_current` bookkeeping; breaking-news bump cascade with band floors, ON_HOLD, slot release, call-in ranking/confirm/expiry/resolve; embargo-at-schedule; slot capacity and 30-minute-gap (inclusive boundary) conflicts; supersede validation ordering; pagination/error envelope shapes; entity-backed vs opaque auth for all nine roles; and fresh-boot empty store + default clock via the exact `bash start.sh` evaluator contract.

One bug was found and fixed during testing: the slot-gap separation formula (now `window_start - other.window_end &gt; 30min or other.window_start - window_end &gt; 30min`, so an exact 30-minute gap conflicts as the PRD requires).

## Step 5: Generate Unit Tests — 2026-08-15T01:02:00.000Z

Generation complete. All audits pass.

## Report

**Task**: test infrastructure + test suite for `task_1895_newsroom_assignment_editorial_workflow` (metro newsroom editorial workflow — 10 entities, 9 roles, 45 endpoints, OCC on story versions, 3-hop bump cascade, payroll OT, dual-variant scoring).

### test_helpers/ (9 files)
- `types.py` — status/role enums + TypedDicts; `ReviewRecord`/`AnalyticsReport` correctly omit `updated_at`/`version` (immutable measurements per PRD §2.5)
- `api_client.py` — 64 methods, one per PRD endpoint (incl. `/_clock/set_current_utc` and the ops scheduler)
- `api_errors.py` — all 29 error ids with the PRD §5 HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions + `assert_active_count_invariant` / `assert_reserved_count_invariant`
- `factories.py`, `constants.py` (bump floors, 2400-min OT threshold, tier multipliers, 60-min call-in TTL, etc.)
- `test_users.py` — opaque `NewsDirector` shared constant; per-instance `make_<role>_headers(staff_id)` builders for all 8 entity-backed roles
- `fixtures.py` — roster builder (`setup_newsroom`), pitch→greenlight, assignment propose/accept, `drive_story_to_cleared`, `setup_scheduled_story`, `setup_published_story`, corrections/analytics/breaking-event composites, with identity threading throughout

### test_suite/ (10 files, 93 tests)
`test_01` staff/auth/404s · `test_02` pitch intake &amp; rework cycle · `test_03` pipeline/reviews/SoD/review-OCC · `test_04` assignment lifecycle/overlap/cap/live-state/counter/priority-pair · `test_05` costs &amp; payroll rounding · `test_06` slots &amp; scheduling/OCC/capacity/embargo/invariants · `test_07` priority scores · `test_08` publication &amp; analytics · `test_09` corrections &amp; retraction cascade · `test_10` breaking news &amp; call-ins.

### Audit results
- **Coverage**: 18/18 difficulty instances with ≥2 tests (36); 57/57 non-stub corner instances with ≥1 test (57). All 7 `excluded_because:` stubs untranslated; their `difficulty_instance` pointers all resolve (space-separated `rule / name` format).
- **Tags**: every one of the 93 test functions ends with exactly one `Design: Difficulty/...` or `Design: Corner/...` line resolving to a real instance; no dual/untagged tests; no skip/xfail markers.
- **PRD citations**: 152 quoted passages across all docstrings verified verbatim against `PRD.md` (whitespace-collapsed grep), including the §2.7 pipeline-order sentences that legitimize the two priority-pair and OCC-precedence tests.
- **PRD-first filter**: every emitted instance has verbatim PRD coverage and a uniquely-derived outcome; zero instances needed skipping.
- **Collection**: `pytest --collect-only` passes (93 tests).

### One translation repair worth flagging
Corner instance `calculations/analytics_blend_uses_only_settled_active` was internally inconsistent: its literal setup greenlights story2 at clock 06:30 with deadline 2026-08-04 (65.5h out → desk_base 24.71 → blend 170.83), contradicting its own asserted 169.20. I kept the asserted value verbatim and moved story2's deadline to 2026-08-05 (&gt;72h out → pressure clamps to 0 → desk_base exactly 22.00), documented in a test comment. Also, `expires_at`/`published_at` assertions compare to minute precision (`startswith`) to respect the PRD's three-fractional-digit ISO format without over-pinning serialization.

## Step 7: Run Tests and Iterate — 2026-08-15T01:15:00.000Z

All 8 rounds pass 93/93. Clean sweep achieved.

## Summary

- **Iterations run**: 2 (initial sweep → 1 fix → verification sweep, all 8 rounds clean).

- **Tests deleted**: none. Every failing test traced to PRD-verbatim rules; no PRD-silence or unique-derivability deletions were warranted.

- **Fixes applied to `test_helpers/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1895_newsroom_assignment_editorial_workflow/test_helpers/fixtures.py` — `add_staff_to()`: the per-instance header builder was looked up by the arbitrary ctx key (`_ROLE_BUILDERS[key]`, which only contains base keys like `"reporter"`), so any test adding a second staff member of an existing role (`"reporter_b"`, `"reporter_c"`, `"reporter_d"`, `"reporter_e"`, `"managing_editor_2"`) crashed with `KeyError` before issuing a single request. Fixed by selecting the header builder from the PRD §2.1 role axis — a new `_CAPABILITY_BUILDERS` map keyed by the staff member's `role_capability` (REPORTER→Reporter, DESK_EDITOR→AssignmentEditor, MANAGING_EDITOR→ManagingEditor, ANALYST→AnalyticsProducer, NEWS_DIRECTOR→opaque NewsDirector, etc.) — making the fixture's identity threading consistent with PRD's entity-backed role model regardless of the ctx label.

- **Fixes applied to `implementation/`**: none. The implementation was already PRD-faithful; all 5 failures were the same upstream fixture bug (the TRIAGE HINT case: ≥5 failures sharing one setup error).

- **Failing tests resolved (deterministic across all 8 rounds)**: `test_08::TestKillRules::test_kill_cancels_open_assignments`, `test_08::TestSupersede::test_supersede_link_and_reverse_filter` (flaky round-ordering victim of the same fixture), `test_09::TestCorrectionApproval::test_sod_correction_self_approve`, `test_10::TestBumpIntersectionGuard::test_only_intersecting_assignment_bumps`, `test_10::TestHoldResumeBubbleUp::test_accept_on_held_story_resumes_to_draft`, `test_10::TestCallInSelector::test_selector_ranking_and_tiebreak` — all were `KeyError` in `add_staff_to`, now passing 8/8 rounds.

## Step 8: Finalize PRD — 2026-08-15T01:20:00.000Z

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1895_newsroom_assignment_editorial_workflow/workspace/PRD_FINALIZED.md` — a verbatim, byte-identical copy of `PRD.md` (verified with `cmp`).

**Line counts / %-delta**: PRD.md = 323 lines, PRD_FINALIZED.md = 323 lines, delta = 0 lines (0.0%).

**Changes**: none — no inserts, no revisions.

### Audit conclusion

The `<step_7_diff>` contains exactly one change: a `test_helpers/fixtures.py` repair (`add_staff_to()` now selects its per-instance header builder from a `_CAPABILITY_BUILDERS` map keyed by the staff member's `role_capability`, instead of `_ROLE_BUILDERS[key]` which only contained base ctx labels and crashed with `KeyError` on `"reporter_b"`, `"reporter_c"`, `"managing_editor_2"`, etc.). There were zero `implementation/` changes and zero test deletions.

This item reveals **no PRD silence and no PRD/implementation mismatch**:

- **(a) Subject**: how identity headers (`X-User-ID` / `X-User-Role`) relate to a staff member's `role_capability` — i.e., the PRD §2.1 two-vocabulary role model.
- **(b) Implementation paths enumerated and read**:
  - `server/auth.py:34-49` (`auth()`) — rejects missing/unknown headers; entity-backed roles (all but `NewsDirector`) require `X-User-ID` to resolve to an existing `StaffMember`; **no coherence check** between header role and `role_capability`. This is exactly PRD §2.1 ("whose `X-User-ID` does not resolve to an existing staff member") plus §2.1's explicit statement that the capability enums are "independent of the CamelCase header roles above", and §2.7 step 1 ("headers present, role recognized, and the entity-backed user resolved" — three checks, no more).
  - `server/routes_staff.py:60-68, 83-85` — `role_capability` validated as an enum at creation and used as a roster filter (PRD §2.7 step 3, §3.1).
  - `server/routes_assignments.py:67-71` — `assignment_role == role_capability` capability-match check (PRD §3.3, §2.7 step 11).
  - `server/routes_breaking.py:157, 180` — hop-two remaining-REPORTER check and call-in eligibility `role_capability in (REPORTER, PHOTOGRAPHER)` (PRD §3.8).
  - `server/serialize.py:23` — `role_capability` in staff representation (PRD §3.1).
  - All five `add_staff_to` callsites in `test_suite/` (test_06:281,348; test_08:111; test_09:62; test_10:130,176,312-318) — all pass standard enum capabilities (REPORTER, MANAGING_EDITOR, PHOTOGRAPHER); the `NEWS_DIRECTOR→opaque` branch of the fixture map is never exercised.
- **(c) Wording adjustment**: none needed — every enumerated path is already uniquely pinned by existing PRD prose.

The six formerly failing tests (`test_08::test_kill_cancels_open_assignments`, `test_08::test_supersede_link_and_reverse_filter`, `test_09::test_sod_correction_self_approve`, `test_10::test_only_intersecting_assignment_bumps`, `test_10::test_accept_on_held_story_resumes_to_draft`, `test_10::test_selector_ranking_and_tiebreak`) each quote their governing PRD sentences verbatim in their docstrings and assert exactly that behavior; all failures were the pre-request `KeyError` in the fixture, not behavioral divergence. The fixture's capability→header-role mapping is a test-side convenience choice the PRD deliberately leaves uncoupled (and the implementation honors that independence), so nothing about it constrains a fresh implementer. A reader of PRD.md alone already produces a behaviorally equivalent codebase.

## Step 9: Complete PRD — 2026-08-15T01:35:00.000Z

The diff is exactly as intended — 21 targeted changes, no collateral edits. Task complete.

## Summary

**Source vs output**: `PRD_FINALIZED.md` (323 lines / 52,816 chars) → `PRD_COMPLETED.md` (325 lines / 55,661 chars), delta **+2 lines, +2,845 chars**. Source was copied from `PRD_FINALIZED.md` (it exists); only `PRD_COMPLETED.md` was edited.

**Counts**: 16 ambiguity-pins, 5 mismatch-revisions (21 changes total).

**Changes** (PRD section — insert|revise — ambiguity|mismatch — what changed — impl ref):

- §2.2 — revise — ambiguity — `api_request_timestamp` pinned as stamped from the logical clock — `implementation/server/envelope.py:11-15`
- §2.2 — insert — ambiguity — undefined route/unsupported method yields `ERR_NOT_FOUND` (404) in the standard error envelope — `implementation/app.py:36-43`
- §2.3 — revise — mismatch — out-of-range `limit`/`offset` are clamped (limit into 1–100, offset up to 0) and non-integer values fall back to defaults, rather than rejected — `implementation/server/util.py:112-125`
- §2.3 — insert — ambiguity — filter query params are exact-equality matches, not validated against enum domains; non-matching values yield empty pages — e.g. `implementation/server/routes_staff.py:83-91`
- §2.3 — revise — mismatch — dropped the false "created_at values are distinct" claim (logical clock freezes timestamps); pinned tie-break by creation/request-arrival order — `implementation/server/util.py:128-129`
- §2.4 — revise — ambiguity — clock-set applies the supplied instant verbatim, no later-than-current requirement — `implementation/server/routes_ops.py:45-53`
- §2.7 — revise — mismatch — swapped pipeline steps 3 and 4: path-parameter existence is resolved before request-body schema (every nested route calls `get_*` before parsing the body) — e.g. `implementation/server/routes_stories.py:177-183`
- §2.11 — revise — mismatch — `active_assignment_count`/`reserved_count` recomputes update the field in place without bumping the owner's `version`/`updated_at`; only `correction_count` rides a real owner mutation — `implementation/server/calc.py:174-195` (no `touch`)
- §3.1 — insert — ambiguity — staff PATCH: omitted or explicit-null fields left unchanged — `implementation/server/routes_staff.py:119-127`
- §3.1 — insert — ambiguity — payroll response `week_start` rendered as ISO calendar date `YYYY-MM-DD` — `implementation/server/routes_staff.py:174-180`
- §3.2 — insert — ambiguity — greenlight responds 200 with the updated pitch (story read back via `greenlit_story_id`) — `implementation/server/routes_pitches.py:165-168`
- §3.2 — revise — mismatch+ambiguity — both `DESK` and `ANALYTICS` reads recompute the desk base from the source pitch against the current logical clock (not the stored figure); invalid `variant` → `ERR_VALIDATION` — `implementation/server/routes_stories.py:363-373`, `implementation/server/calc.py:81-88`
- §3.4 — insert — ambiguity — story PATCH semantics: omitted fields unchanged, explicit-null `word_count` treated as omitted, explicit-null `embargo_until` clears it, any validated PATCH bumps `version` even when nothing changes — `implementation/server/routes_stories.py:109-131`
- §3.4 — insert — ambiguity — FactChecker filing `LEGAL` / LegalReviewer filing `FACT_CHECK` → `ERR_FORBIDDEN` (403), evaluated after body schema and before the OCC check — `implementation/server/routes_stories.py:185-193`
- §3.5 — insert — ambiguity — publication leaves story `slot_id` in place and does not recompute slot `reserved_count`; slot story collections include already-published stories; checkpoint id lists are in creation order — `implementation/server/routes_ops.py:18-42`
- §3.5 — insert — ambiguity — supersede "non-terminal" means exactly not `RETRACTED`/`KILLED`; a `PUBLISHED` story may be the follow-up target — `implementation/server/routes_stories.py:352-355`
- §3.6 — revise — ambiguity — story `version` increments exactly once per issuance, even when issuance also retracts and voids analytics (single `touch`) — `implementation/server/routes_corrections.py:61-78`
- §3.7 — insert — ambiguity — duplicate-window uniqueness counts existing reports of any status, including `VOID` — `implementation/server/routes_stories.py:487-497`
- §3.8 — insert — ambiguity — hop two re-evaluates only stories that lost at least one assignment to hop one — `implementation/server/routes_breaking.py:141-163`
- §3.8 — insert — ambiguity — call-in ranking's final tie-break (after count and `created_at`) is staff creation order — `implementation/server/routes_breaking.py:182-184`

**Notable design facts verified during the walk**: all validation-order-sensitive endpoints (accept, schedule, file-review, complete-edit, corrections approve, ingest) follow the impl's actual order of auth → role → path → body schema → FK → ownership → OCC → from-state → SoD → gates; the rework-limit check correctly sits after the from-state check; error catalog and endpoint role tables matched impl exactly with no changes needed.
