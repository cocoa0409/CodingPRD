# Worklog — task_1685_4_h_ffa_project_record_management

## Step 1: Create Task Directory — 2026-08-14T07:43:00.000Z

Task directory `tasks/task_1685_4_h_ffa_project_record_management/` and `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher. Step 1 treated as DONE per command args; no index scan performed, no other task directory touched.

## Step 3: Copy Shared Files — 2026-08-14T07:44:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1685_4_h_ffa_project_record_management/workspace/INSTRUCTION.md` (1424 bytes). Executed early, in parallel with Step 2's scaffold subagent, since it has no dependency on scaffold output.

## Step 2: Generate Scaffold — 2026-08-14T08:23:00.000Z

All three scaffold artifacts are generated and pass clean lint. Here is the summary.

## Summary

Generated the scaffold for `task_1685_4_h_ffa_project_record_management` purely from the scenario description and the skill spec (no sibling tasks were inspected). Targeted maximum difficulty (Expert-plus): a compliance/audit + posture-driven-gating archetype with segregation-of-duties role model, cyclic record-book review loop, dual-variant scoring, and two OCC concurrency rules.

**Files written (line counts):**
- `/home/ubuntu/github/CodingPRD/tasks/task_1685_4_h_ffa_project_record_management/SCAFFOLD.yaml` — 2007 lines (§1.0–§1.7; no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1685_4_h_ffa_project_record_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1679 lines (single top-level key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1685_4_h_ffa_project_record_management/SCAFFOLD_CORNER_DESIGN.yaml` — 942 lines (single top-level key `scaffold_corner_design`)

**Key metrics:**
- Entity count: **17**
- State machine count: **10** (Member, Project, RecordBook, FairEntry, AwardApplication, ScholarshipApp, Volunteer, Meeting, AnimalTag, StallAssignment)
- Calculation count: **7** (record_book_score [dual-variant], record_book_late_days, award_rubric_score, scholarship_points [pinned round-per-line], member_eligibility_posture, ownership_days, volunteer_screening_score [pinned-order circular])
- Validation rule count: **15** (ordered, priority 1–15)
- Endpoint count: **85** (includes `POST /api/_clock/set_current_utc` test-driving clock with pinned default 2026-08-01T00:00:00Z)
- Error catalog size: **15**
- Concurrency rules: **2** (record-book submit OCC; STAR-nominate club OCC)
- §1.8 difficulty instance count (non-stub): **18** (exactly 2 per each of the 9 rules, all differentiated per §0.5)
- §1.9 corner instance count (non-stub): **17** (across entities, state_machines, calculations, endpoints, errors, rbac, cross-cutting layers)

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (471 calls scanned, 0 violations)

**Notable issues caught and fixed during self-audit (beyond the mechanical linter):**
- Fixed YAML flow-sequence parse errors in `grounds` lists (nested brackets/quotes → block style).
- Corrected an OCC grounding bug: several instances captured `expected_club_version` from `AwardApplication.version` instead of the Club's version; inserted `GET /api/clubs/{id}` captures before each nominate.
- Fixed an end-state replay bug in `pen_capacity_aggregate_count` (removed posture-blocking `confirm` calls — stall assignment has no CONFIRMED precondition) and in `ownership_days_exactly_at_threshold` (added attendance + approved record book + verified tag so the member genuinely reaches ELIGIBLE before confirm).
- Tightened the treasury priority instance so the latent fiscal overdraw is genuinely present (reimbursement 800 vs remaining balance 200).
- Resolved enum-closure gaps by adding `POST /api/ledger-entries/{id}/void`, `POST /api/treasury-transactions/{id}/void`, and `POST /api/animal-tags/{id}/reject` (plus an AnimalTag state machine), and registered all in RBAC.

## Step 4: Generate PRD — 2026-08-14T08:49:00.000Z

All checks pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1685_4_h_ffa_project_record_management/workspace/PRD.md`.

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1685_4_h_ffa_project_record_management/workspace/PRD.md` — 328 lines (tables are single-line rows; 85 endpoint rows + 15 error rows).

**Section list**:
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC, 2.2 API Response Structure (verbatim block), 2.3 Pagination, 2.4 Resource Identity/Timestamps/Version Semantics, 2.5 Program-Year Logical Clock, 2.6 Numeric Precision & Rounding, 2.7 Optimistic Concurrency Control, 2.8 Nested Resource Retrieval & Caller Ownership, 2.9 Validation Priority Order
- §3 Business Logic (9 subsections): 3.1 Club Setup & Treasury, 3.2 Volunteer Screening, 3.3 Member Lifecycle, 3.4 Projects & Livestock Tagging, 3.5 Record Books, 3.6 Meetings/Rooms/Attendance, 3.7 Member Eligibility Posture, 3.8 Fair Entries & Stall Assignments, 3.9 Awards & Scholarships
- §4 Endpoint Definitions (4-column table, 85 rows), §5 Error Code Catalogue (2-column table, 15 rows)

**Per-§1.x scaffold coverage**:
- §1.0 `response_envelope` → §2.2 (verbatim) + §2.3 (limit 10/1/100, offset 0, created_at ascending, meta fields)
- §1.1 `entities` (17 entities, 60 fields) → scattered across §3.1–3.9; `common_fields: false` set (LedgerEntry, Attendance, ScreeningEvent, TreasuryTransaction) named explicitly in §2.4
- §1.2 `state_machines` (11 machines, all transitions w/ preconditions + side effects) → §3.3–3.9 via state-pair framing (`DRAFT → SUBMITTED` etc.)
- §1.3 `calculations` (all 7: record_book_score both variants, late_days, rubric, scholarship_points, posture, ownership_days, screening_score) → §3.2/3.5/3.7/3.8/3.9 with constants embedded and rounding order pinned in §2.6
- §1.4 `validations` (all 15) → §2.9 as an explicit ordered pipeline + trigger conditions co-located in §3
- §1.5 `endpoints` (85) → §4 table + §3 narratives; all request/query/path identifiers covered
- §1.6 `errors` (15) → §5 table + every ID mentioned in §2/§3
- §1.7 `roles` (3, with identity translations for opaque ProgramAdmin / entity-backed Volunteer / Member) → §2.1
- `concurrency_rules` (2) → §2.7 with `expected_record_book_version` / `expected_club_version`, `ERR_STALE_VERSION` 412, stale-version framing only

**Hard Contract reports**:
```
Field coverage check:
- entities[].fields: 60 required, 60 present, 0 missing
- endpoints[].request_body/input: 51 required, 51 present, 0 missing
- endpoints[].query_params: 0 required (filters folded into input lists; county_code/room_id/club_id/project_id/member_id/record_book_id/linked_award_application_id all present)
- endpoints[].path_params: 1 required (id), 1 present
Status: PASS (two passes run; pass 1 found entry_status missing, repaired in §3.5, pass 2 clean)

Rule coverage check:
- validations[] with priority: 15 checked, 15 expressed in §2.9 ordered prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write capability + occ field + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 24 checked, 24 fully expressed, 0 missing
- calculations[]: 7 checked, 7 fully expressed (constants + boundaries + rounding order), 0 missing
- validations[] conditions: 15 checked, 15 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed in workflow narratives (suspend→project drops, mark-held→club-wide posture recompute, nominate→club counter+version, treasury credit/debit/reversal, etc.), 0 missing
- entities[].fields[] structured content: defaults, enums, and nullability reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (verify/reject, award/deny, grant/decline, clear/deny, withdraw×2, scratch×2, drop×2, submit×2), all rendered with equal density and explicit asymmetries, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 170
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Zero-Silence Rule judgments**:
- **Stated fully** (boundary/exactness rules, since they come from the scaffold itself, not the withheld test indices): inclusive thresholds (75.00 attendance, 85.00 GOLD, exactly-60/30 ownership days, score ≥ 40, points ≥ 30, quota "below two"), the pinned scholarship rounding order with a self-derived worked example (two A-grade projects → 11 + 11 = 22, which discriminates round-per-line from sum-then-round), half-open room-overlap semantics ("meetings that merely touch do not conflict"), the three-step pinned screening-score order, and the submit-vs-resubmit precondition asymmetry (ledger-entry requirement only on `DRAFT → SUBMITTED`).
- **Phrased carefully**: (1) `star_nomination_count` — the entity description ("count of STAR apps in NOMINATED/ENDORSED") and the transition side effects (no decrement on `ENDORSED → WITHDRAWN` or `EVALUATED → DENIED`) are in slight tension; I rendered the description as intent in §3.1 and the event-driven maintenance (+1 on STAR nominate, −1 on STAR award or withdraw-from-NOMINATED, nothing on withdraw-from-ENDORSED or deny) as the operative rule in §3.9, since tests walk transitions. (2) The fair-entry-confirm posture precondition (`ELIGIBLE` required) has no scaffold-nominated error ID, so I stated the requirement without inventing an error code. (3) Uniqueness constraints (club name per county, volunteer email, tag number per program year, room name, pen label) are stated descriptively without attaching an uninvented error ID. (4) No race-condition framing in OCC prose — strictly stale-version language per the skill.

No difficulty/corner design files or sibling tasks were opened.

## Step 5: Generate Unit Tests — 2026-08-14T09:18:00.000Z

All checks pass. Generation complete — here is the summary.

## Files written

**`test_helpers/`** (Stage 1) — under `/home/ubuntu/github/CodingPRD/tasks/task_1685_4_h_ffa_project_record_management/test_helpers/`:
- `types.py` — 17 entity TypedDicts + 20 enums; audit-line entities (LedgerEntry, Attendance, ScreeningEvent, TreasuryTransaction) correctly omit `updated_at`/`version` per PRD §2.4
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (~60 methods)
- `api_errors.py` — `ApiErrorId` (15 errors) + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` with mutable-vs-audit-line common-field branching
- `factories.py` — input-only payload factories with uuid-unique names/emails/labels
- `constants.py` — thresholds (75% attendance, 40 clearance, star quota 2, 60/30 ownership days, tier 85/70/55, etc.) and fixed deadlines
- `test_users.py` — opaque `program_admin_headers`, entity-backed `make_volunteer_headers`/`make_member_headers` builders, `NO_AUTH_HEADERS`
- `fixtures.py` — composite helpers: `setup_club_with_volunteers`, `setup_active_member_with_project`, `build_approved_record_book`, `record_attendance_and_hold`, `setup_eligible_member`, `setup_confirmed_fair_entry`, `nominate_award` (re-reads club version for OCC), `setup_nominated/endorsed/evaluated_award`, `setup_member_with_completed_projects`, `setup_open_scholarship_app`, treasury helpers
- `__init__.py` — barrel export

**`test_suite/`** (Stage 2) — `conftest.py` + 8 files: `test_01_club_setup_and_listing.py`, `test_02_volunteer_screening.py`, `test_03_member_project_lifecycle.py`, `test_04_record_book_review.py`, `test_05_meetings_and_posture.py`, `test_06_fair_entries_and_stalls.py`, `test_07_awards_and_scholarships.py`, `test_08_treasury.py`.

## Tests emitted

- **Queue A (Difficulty): 40 test functions across all 18/18 instances, each ≥2.** Includes the dual-variant scoring divergence (provisional 81.00 vs final 80.00), scholarship round-per-line 37 vs 36, screening pinned-order (50 not 64), revision cycle to APPROVED, suspend depth-3 cascade, approve→posture cascade, both validation-priority pairs (ERR_INVALID_STATE wins), ownership 60/59/30-day boundaries, star quota 2-of-2 boundary, posture/screening cross-entity gates, room half-open adjacency, pen aggregate capacity, treasury and star-quota invariants.
- **Queue B (Corner): 19 test functions across all 17/17 non-stub instances (no stubs exist in this corner index), each ≥1.**
- Total: 59 test functions (64 collected by pytest after parametrization).

## Instances skipped

**None.** All 35 instances passed the PRD-first two-condition filter. Three adjudication adjustments were applied where a single assertion or setup step failed unique derivability (instances themselves were fully translated):
1. `Corner/entities/club_create_returns_201_and_system_fields` — the `version == 1` assert was omitted (PRD §2.4 never pins the initial version value; only "increments by exactly one on every mutation"). All other asserts (201, ACTIVE, zero treasury/star count, system fields) are PRD-covered and kept.
2. `Difficulty/resource_temporal_overlap/pen_capacity_aggregate_count` — stall assignments were built on CONFIRMED entries instead of the recipe's ENTERED entries, because PRD §4/§3.8 describe stall assignment as applying to a "confirmed fair entry"; CONFIRMED works under both readings and leaves the capacity claim intact.
3. `Difficulty/non_linear_state_machine/award_application_fork_withdraw_vs_evaluate` — the ENDORSED-withdraw test asserts only `status == WITHDRAWN`; whether the star count decrements on the ENDORSED fork is ambiguous between PRD §3.9 ("simply retires the application") and §3.1's tracking definition (branch-asymmetry silence pattern), so no count assertion was made on that branch.

## Stage 2 self-check result

- **Tag audit: PASS** — 59/59 tests carry exactly one `Design:` line at docstring end; all 59 tags resolve to live instances (verified programmatically against both YAMLs); zero shortfalls (A: 18/18 instances ≥2 tests; B: 17/17 ≥1); zero tests point at stubs (no stubs exist).
- **Citation audit: PASS** — all 87 quoted docstring spans verified verbatim against `PRD.md` (whitespace-normalized literal match); every asserted `error_id` appears in PRD prose (§2/§3), not just the §5 table.
- **No `skip`/`skipif`/`xfail` markers; no scaffold references in generated code; `python -m py_compile` clean; `pytest --collect-only` collects 64 items with all `test_helpers` imports resolving.**

## Step 6: Generate Implementation — 2026-08-14T09:21:00.000Z

All 85 PRD endpoints registered — none missing, none invented. Implementation complete and fully verified.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1685_4_h_ffa_project_record_management/workspace/implementation/`):

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 10 | Launcher (details below) |
| `requirements.txt` | 1 | `flask>=3.0` |
| `app.py` | 73 | Entry point, blueprint registration under `/api`, envelope error handlers |
| `db.py` | 37 | In-memory store: 17 empty dicts keyed by id + insertion sequence |
| `clock.py` | 51 | Program-year logical clock (default `2026-08-01T00:00:00Z`, never wall-clock) |
| `errors.py` | 38 | `ApiError` + all 15 catalog error IDs |
| `response.py` | 37 | Success/error envelopes (`meta`/`response_type`/`data`) |
| `middleware.py` | 101 | Auth priorities 1-2, caller resolution/ownership (priority 4), 404 helper, `touch()` version bump |
| `validation.py` | 148 | Priority-14 shape validators, pagination parsing (`limit`/`offset`) |
| `services/calc.py` | 240 | All six calculations |
| `services/serialize.py` | 220 | Per-entity serializers (audit lines omit `version`/`updated_at`) |
| `routes/` | 2,038 | 13 modules: clock_routes, clubs, volunteers, members, projects, animal_tags, record_books, ledger_entries, meetings (rooms+attendance blueprints), fair (pens+stalls blueprints), awards, scholarships, treasury |

**Endpoints implemented: 85/85** — verified programmatically against the Flask URL map (no missing, no extra).

**State machines implemented (11):** Member (ENROLLED/ACTIVE/SUSPENDED/GRADUATED with suspend cascade dropping PLANNED/ACTIVE projects), Project (with ACTIVE-drop rejecting in-flight record books), RecordBook (DRAFT/SUBMITTED/UNDER_REVIEW/RETURNED/APPROVED/REJECTED incl. resubmission), FairEntry (role-split scratch: member scratches ENTERED, volunteer scratches CONFIRMED), AwardApplication (full chain incl. star-slot increments/decrements, ENDORSED-withdraw deliberately not releasing the slot per PRD 3.9), ScholarshipApp, Volunteer screening, Meeting, AnimalTag, StallAssignment, plus TreasuryTransaction/LedgerEntry status lifecycles.

**Calculations implemented (6):** `record_book_score` (provisional = plain weighted sum; final = bonus-cap-then-penalty pinned order, Decimal ROUND_HALF_UP 2dp), `record_book_late_days` (whole dates past 2026-07-15), `award_rubric_score` (inclusive tier boundaries; leadership capped at 20), `scholarship_points` (per-line round-half-up then sum: A=11/B=8/C=7), `member_eligibility_posture` (EXCUSED-excluded attendance %, approved-book leg, livestock verified-tag leg, ELIGIBLE/CONDITIONAL/INELIGIBLE), `ownership_days` (earliest VERIFIED tag, tie-break created_at then tag_number; 60-day BEEF / 30-day SHEEP/SWINE inclusive minimums), `volunteer_screening_score` (pinned 3-step cap-then-min-then-score).

**Validation/error handling:** Strict PRD §2.9 priority pipeline — 401 auth → 403 RBAC → 404 existence (left-to-right) → 403 caller ownership/entity resolution → 409 state → 422 SoD → 422 screening → 409 room overlap (half-open, touching allowed) → 422 pen capacity → 422 star quota → 422 ownership period → 422 treasury solvency → 422 referential integrity → 400 request shape → 412 OCC (always last). OCC: `expected_record_book_version` on submit, `expected_club_version` on nominate (all tracks, per §2.7). Begin-review parent/guardian SoD is documented in code as structurally inert (no parent/guardian field exists in the data model). Uniqueness (club name+county, volunteer email, room name, pen label, tag number per program year) → 400.

**Verification:** 4 live smoke passes plus a 112-call full-route sweep all pass — fresh-boot empty store confirmed on every restart; scoring math, posture transitions, star quota, boundaries (85.00 GOLD, exactly-30-day ownership), pen capacity release/reuse, and treasury solvency/reversal all behave per spec.

**start.sh contract confirmed:** reads `$PORT` (default 10000 via `app.py`), binds `0.0.0.0`, runs in the foreground via `exec python3 app.py`, and guards the dependency install (`if ! python3 -c "import flask"`) so per-test-server reboots skip `pip install`. Verified by booting with `bash start.sh` directly.

## Step 7: Run Tests and Iterate — 2026-08-14T09:32:00.000Z

Clean sweep — all 8 rounds pass 64/64.

**Summary**

- **Iterations run**: 2 (initial sweep identified 3 deterministic failures across all 8 rounds; verification sweep after fixes passed 8/8 rounds, 64/64 tests each).

- **Tests deleted**: none.

- **Fixes applied to `test_suite/`** (test bug, STEP 2 — plumbing, not assertion weakening):
  - `/home/ubuntu/github/CodingPRD/tasks/task_1685_4_h_ffa_project_record_management/test_suite/test_07_awards_and_scholarships.py` — `TestStarQuotaBoundary._star_member` referenced the bare name `api` (the pytest fixture) without receiving it, causing `NameError: name 'api' is not defined` in `test_second_star_nomination_succeeds` and `test_third_star_nomination_rejected`. Threaded the fixture through: signature changed to `_star_member(self, api, ctx, birth_date)` and all 5 call sites updated. The asserted PRD §3.9 quota rule was verbatim-covered and faithful; only the fixture plumbing was broken.

- **Fixes applied to `implementation/`** (STEP 3 — PRD-covered, uniquely derivable, test faithful):
  - `/home/ubuntu/github/CodingPRD/tasks/task_1685_4_h_ffa_project_record_management/workspace/implementation/routes/members.py` — `suspend_member` dropped PLANNED/ACTIVE projects to DROPPED but omitted the record-book side effect. PRD §3.3 states suspension "drops every project of the member that is still PLANNED or ACTIVE" and §3.4 states "Dropping an ACTIVE project also rejects its record book if that book is still in flight — a book in DRAFT, SUBMITTED, UNDER_REVIEW, or RETURNED moves to REJECTED". Added the in-flight book rejection (mirroring the existing `drop_project` logic in `routes/projects.py`) for ACTIVE projects dropped by the suspend cascade, fixing `test_suspend_drops_active_project_and_rejects_draft_book`. APPROVED/REJECTED books remain untouched per PRD.

- **PRD coverage verification**: both rules traced to verbatim PRD sentences (§3.3 line 152, §3.4 line 158, §3.9 star quota). No flaky tests observed — the 3 initial failures were deterministic across all 8 rounds, and no new failures surfaced in the post-fix sweep.

## Step 8: Finalize PRD — 2026-08-14T09:38:00.000Z

Done. `PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1685_4_h_ffa_project_record_management/workspace/PRD_FINALIZED.md`.

## Summary

**Line counts / delta:** PRD.md 328 lines, PRD_FINALIZED.md 328 lines — 0% line-count delta (one line revised inline, no insertions of new lines/sections).

**Changes (one total):**
- §3.3 — revise — extended the suspension sentence with `; each of these suspension drops is a drop in the full sense of §3.4, so a project that was ACTIVE also rejects its record book if that book is still in flight` — pins that the suspend cascade rejects in-flight record books of formerly-ACTIVE projects — `implementation/routes/members.py:99-107` (mirroring `implementation/routes/projects.py:121-128`).

**Step-7 items disposition:**
- `test_suite/test_07_awards_and_scholarships.py` `_star_member` fixture fix — pure test plumbing (`NameError` on the `api` fixture); zero behavioral content; PRD §3.9 star-quota rule verbatim-covered and faithful; no implementation change → **no PRD edit**.
- `implementation/routes/members.py` `suspend_member` fix — although Step 7 traced §3.3/§3.4 as verbatim coverage, the original implementation (built from this PRD) demonstrably omitted the book rejection, proving a fresh reader can resolve the ambiguity the other way: §3.3's suspension text never mentions record books, and §3.4's rejection sentence sits in a paragraph whose declared subject is the member's own drop act. The implementation now pins the generic reading → **one minimal PRD edit** (above).

**Per-edit pre-edit search log:**
- Edit 1 (§3.3 suspension sentence):
  - (a) Subject: whether suspension-triggered project drops carry §3.4's record-book rejection side effect.
  - (b) Impl paths enumerated and read/grepped: `routes/members.py:83-109` (suspend cascade; `was_active`-gated rejection of DRAFT/SUBMITTED/UNDER_REVIEW/RETURNED books, `touch` on each project and book); `routes/projects.py:108-129` (member drop; identical `was_active` gate); `routes/record_books.py:203-213` (volunteer reject endpoint, UNDER_REVIEW → REJECTED — not a drop); `routes/record_books.py:29-62` (book creation has no project-state gate, so PLANNED projects can hold DRAFT books which both drop paths leave untouched); `routes/members.py:124-140` (graduation does NOT drop projects); repo-wide greps for `DROPPED` (exactly 2 sites: members.py:97, projects.py:119) and `REJECTED` (3 book sites + unrelated animal-tag reject); PRD §2.4 line 84 already names "a suspension dropping a member's projects" as a version-bumping cascade (consistent, left verbatim).
  - (c) Wording adjustment: kept the ACTIVE-only scope ("a project that was ACTIVE also rejects...") so PLANNED-project drops (which may hold DRAFT books per the un-gated create path) are not mis-described; phrased as a cross-reference to §3.4 rather than restating the status list, so §3.4 stays the single source for the in-flight set and the APPROVED/REJECTED exemption; attached the clause strictly to the suspension sentence so the graduation and member-drop paths are untouched.

## Step 9: Complete PRD — 2026-08-14T09:56:00.000Z

All edits verified against implementation behavior. The task is complete.

## Summary

**Files:** Source `/home/ubuntu/github/CodingPRD/tasks/task_1685_4_h_ffa_project_record_management/workspace/PRD_FINALIZED.md` (328 lines, 46,117 chars) → produced `/home/ubuntu/github/CodingPRD/tasks/task_1685_4_h_ffa_project_record_management/workspace/PRD_COMPLETED.md` (328 lines, 50,999 chars; **+4,882 chars, +0 lines** — all changes are inline, no new sections).

**Counts:** 19 ambiguity-pins, 8 mismatch-revisions (27 total changes, all in-paragraph).

### Ambiguity pins (PRD silent → inserted impl behavior)
- §2.3 — insert — ambiguity — out-of-range/non-integer `limit`/`offset` rejected with ERR_INVALID_REQUEST 400 — implementation/validation.py:107-128
- §2.3 — insert — ambiguity — equal `created_at` ties broken by insertion order (logical clock freezes timestamps) — implementation/validation.py:144-148, db.py:26-33
- §2.4 — insert — ambiguity — `version` starts at 1; a recompute yielding an unchanged value advances neither `version` nor `updated_at`; activation/reinstatement bump the member exactly once despite also recomputing posture — implementation/middleware.py:83, services/calc.py:205-214, routes/members.py:77-79
- §2.8 — insert — ambiguity — ownership rule governs member-called creation endpoints (projects, record books, ledger lines, animal tags, fair entries, award and scholarship applications) — implementation/routes/projects.py:32-33, record_books.py:39-40, ledger_entries.py:38-39, animal_tags.py:30-31, fair.py:83-84, awards.py:37-38, scholarships.py:37-38
- §2.9 item 5 — insert — ambiguity — ERR_INVALID_STATE (409) pinned for every §3 transition precondition lacking a dedicated error (club-ACTIVE on activation, member-ACTIVE on start, APPROVED book on complete/nominate, POSTED-line + ACTIVE-project on submit, DRAFT/RETURNED ledger window, no-open-entries on graduation, ELIGIBLE posture on confirm, ASSIGNED stall on mark-exhibited, CONFIRMED entry on stall assignment, award/deny tier rules, EVALUATED GOLD/SILVER on scholarship submit, 30-point grant floor) — e.g. implementation/routes/fair.py:154, members.py:135, scholarships.py:129
- §2.9 item 14 — insert — ambiguity — uniqueness violations (club name/county, volunteer email, room name, pen label, tag number per program year) rejected with ERR_INVALID_REQUEST 400 — implementation/routes/clubs.py:31-35, volunteers.py:44-47, meetings.py:36-39, fair.py:36-39, animal_tags.py:42-48
- §3.1 — insert — ambiguity — approve accepts solely a POSTED expense reimbursement; any other target (incl. POSTED dues payment) → ERR_INVALID_STATE 409 — implementation/routes/treasury.py:73-75
- §3.1 — insert — ambiguity — recording a dues payment increments the club `version` (immediate credit mutates the club); recording a reimbursement does not touch the club — implementation/routes/treasury.py:52-55
- §3.2 — insert — ambiguity — screening events are not gated on `screening_status`; may accrue before/after clearance — implementation/routes/volunteers.py:118-145
- §3.4 — insert — ambiguity — tagging not gated on project type or status; tag `species` unchecked against project type — implementation/routes/animal_tags.py:20-60
- §3.5 — insert — ambiguity — record-book creation not gated on project status; multiple books per project allowed; `provisional_score`/`final_score` start null — implementation/routes/record_books.py:29-62
- §3.6 — insert — ambiguity — attendance rows unguarded: any meeting status, any member, duplicates permitted — implementation/routes/meetings.py:195-226
- §3.8 — insert — ambiguity — `ownership_days_at_entry` is null when no VERIFIED tag; partial days floored so post-deadline `owned_since` yields a negative count — implementation/services/calc.py:230-236
- §3.8 — insert — ambiguity — ownership minimum keyed on `project_type`; CROPS/FOODS/ROBOTICS entries exempt; null count fails with ERR_OWNERSHIP_PERIOD_SHORT — implementation/routes/fair.py:158-165
- §3.8 — insert — ambiguity — an entry may hold multiple ASSIGNED stalls; no per-entry uniqueness — implementation/routes/fair.py:239-281
- §3.9 — insert — ambiguity — award application's linked record book need not belong to the drafting member (no link check at creation); `rubric_score`/`award_tier`/`nominated_by` start null — implementation/routes/awards.py:24-62
- §3.9 — insert — ambiguity — `scholarship_points` starts null until submission computes it — implementation/routes/scholarships.py:62
- §5 — insert — ambiguity — framework-level rejections: unmatched path → ERR_NOT_FOUND 404; unsupported method → ERR_INVALID_REQUEST at HTTP 405 — implementation/app.py:52-59

### Mismatch revisions (PRD described different behavior → revised to impl)
- §2.9 item 6 — revise — mismatch — begin-review SoD check annotated as never firing (no parent/guardian linkage exists in the data model) — implementation/routes/record_books.py:150-154
- §3.1 — revise — mismatch — "two-letter `county_code`" → "two-character" (impl enforces length 2 only) — implementation/routes/clubs.py:27-29
- §3.1 — revise — mismatch — `star_nomination_count` no longer characterized as "tracks applications sitting in NOMINATED or ENDORSED"; pinned to the actual event rules: +1 on STAR nomination, −1 on STAR award, −1 on withdrawal from NOMINATED only; endorsement, evaluation, denial, and withdrawal from ENDORSED leave it unchanged — implementation/routes/awards.py:129-131,194-198,228-237
- §3.1 — revise — mismatch — treasury `amount_cents` "positive" → "non-negative" (impl accepts 0, matching §2.9 item 14) — implementation/routes/treasury.py:41
- §3.3 — revise — mismatch — `birth_date` no longer "used to derive the member's age division" (impl derives nothing; no age field exists) — implementation/routes/members.py:32, services/serialize.py:50-60
- §3.5 — revise — mismatch — ledger zero-per-kind split (`amount_cents` zero on HOURS lines, `hours` zero on monetary lines) restated as an unenforced usage convention; server requires both fields, validates only non-negativity/type — implementation/routes/ledger_entries.py:52-55
- §3.5 — revise — mismatch — begin-review SoD guard rewritten: structurally inert, any volunteer may begin review, ERR_SEGREGATION_OF_DUTIES never raised here — implementation/routes/record_books.py:150-154
- §4 — revise — mismatch — nominate table cell "(OCC-guarded on the club for STAR)" → "OCC-guarded on the nominee's club, on every track" (impl requires `expected_club_version` for DEGREE/STAR/SCHOLARSHIP alike, per §2.7) — implementation/routes/awards.py:119-125
