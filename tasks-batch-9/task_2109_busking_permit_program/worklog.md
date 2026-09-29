# Worklog — task_2109_busking_permit_program

## Step 1: Create Task Directory — 2026-08-16T18:42:22.834Z

Created `tasks/task_2109_busking_permit_program/` and `tasks/task_2109_busking_permit_program/workspace/`. Index 2109 chosen as max existing index (2108) + 1.

## Step 3: Copy Shared Files — 2026-08-16T18:42:42.922Z

Copied `./INSTRUCTION.md` → `tasks/task_2109_busking_permit_program/workspace/INSTRUCTION.md`. (Run ahead of Step 2's completion; no dependency on the scaffold.)

## Step 2: Generate Scaffold — 2026-08-16T19:53:00.289Z

Generation complete. All three artifacts are written to `/home/ubuntu/github/CodingPRD/tasks/task_2109_busking_permit_program/` and pass `scaffold_lint.py` cleanly.

**Verdict block (verbatim from `python3 skills/prd-bench-scaffold-generator/scaffold_lint.py .`):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    51
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     82
  Calls scanned (§1.8+§1.9):  1143

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Counts**

| Table | Count |
|---|---|
| §1.1 entities | **14** (Zone, Pitch, Performer, PermitApplication, Audition, AuditionScore, Permit, FeeInvoice, LotteryDraw, LotteryEntry, SessionBooking, NoiseReading, Complaint, ClosureOrder) |
| §1.2 state machines | **10** (62 transitions), incl. Permit split into two independent axes `lifecycle_status` × `compliance_status` |
| §1.2.1 concurrency rules | **2** (OCC on PermitApplication.version and Permit.version) |
| §1.3 calculations | **11** (3 carry `variants:`) |
| §1.4 validations | **46** (priority 10 → 88, strictly ascending) |
| §1.5 endpoints | **51** (49 business + `/busking/ops-runs` + `/_clock/set_current_utc`) |
| §1.6 errors | **57** |
| §1.7 roles | **5** (PermitOfficer, Performer, AuditionPanelist, NoiseInspector, Resident; `segregation_of_duties`) |
| §1.8 instances | **18** — 9 rule_ids × 2 |
| §1.9 instances | **90** across 9 sections (82 full recipes + 8 `excluded_because:` stubs) |

**Profile:** expert_plus; primary archetype `temporal_windowing`, secondary `quota_allocation`; layers optimistic_concurrency / cascading_side_effects / dual_variant_calculation / selector_policy; topology **flat**, shape **cyclic**, self-referential FK (`Pitch.fallback_pitch_id`), role model **segregation_of_duties** — the four dimensions the skill flags as under-represented.

**Key difficulty mechanics** (all literals executed in code, not estimated): fee engine with pinned evaluation order (tier + admin rate both keyed on pre-discount gross → 22050, not the plausible-looking 22075) and FULL_SEASON/PRORATED dual variant (16200 vs 6750 on identical inputs); conduct scoring dual variant on a different entity domain (ROLLING_365 → 88/GOOD vs CAREER_WEIGHTED → 75, blocking renewal); audition panel score with pinned per-panelist-then-average rounding (6.91 vs 6.90); two depth-4 cascades from different triggers (complaint uphold → standing → suspension → booking/entry; closure activate → pitch → booking → minute credit); two priority conflicts on different category pairs (state×fiscal, safety×constraint); two overlap geometries on different resources (buffered half-open on Pitch vs closed-interval aggregate capacity on Zone); two conserved quantities (minutes and cents).

**Fixed clock default** `2026-08-01T00:00:00Z` is declared on the `/_clock/set_current_utc` endpoint and asserted by a §1.9 instance.

**Verified beyond the linter:** zero unbound `${var}` placeholders across both design files; all `grounds:` refs resolve into §1.1–§1.7; all 57 error ids referenced by a validation/transition *and* exercised in a design instance; all 51 endpoints exercised by at least one recipe call; all 8 stub targets resolve by name into `SCAFFOLD_DIFFICULTY_DESIGN.yaml`; no forbidden concurrency vocabulary; no `id`-based business decisions (tie-breaks use `created_at ASC`).

## Step 4: Generate PRD — 2026-08-16T20:05:41.588Z

All three hard contracts pass. The PRD is complete and verified on disk.

**Deliverable:** `/home/ubuntu/github/CodingPRD/tasks/task_2109_busking_permit_program/workspace/PRD.md` — 456 lines, 12,194 words, 5 top-level sections (`## 1`–`## 5`), ending cleanly at the last error-catalogue row.

**Structure** (domain-derived, not copied from the example): §1 introduction (3 paragraphs); §2 with 11 subsections (2.1 RBAC, 2.2 verbatim envelope, 2.3 pagination, 2.4 common properties/versioning, 2.5 the program clock, 2.6 rejection precedence, 2.7 OCC, 2.8 units/precision, 2.9 cascade discipline + the two ledger invariants, 2.10 separation of duties, 2.11 path resolution + discovery listings); §3 with 9 workflow subsections (ordinance map → enrollment/application → audition → decision/permit/fee → money/renewal/revocation → session bookings → rotation draws → enforcement → closures + epoch advance); §4 endpoint table (4 columns); §5 error table (2 columns).

**Coverage (machine-verified against SCAFFOLD.yaml):**
- Field-name coverage: 118/118 entity fields, 58/58 request-body identifiers, 22/22 query params, plus all 8 ops-run/clock response fields — 0 missing.
- Endpoints: 51/51 paths present in §4.
- Errors: 57/57 in the §5 table, and all 57 also mentioned with their trigger conditions in §2/§3 prose.
- §3 path purity: 768 backtick tokens scanned, 0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path combos.
- §2.2 matches the canonical `section-2.2-response-structure.md` byte-for-byte.

**Rule coverage highlights:** the full 46-step validation precedence list is stated explicitly in §2.6 (including the two deliberate pre-emptions at `ERR_COMPLAINT_ALREADY_RESOLVED` and `ERR_AUDITION_REQUIRED` ahead of the generic state check); both `concurrency_rules` are expressed with write endpoint + `expected_application_version`/`expected_permit_version` + error id + 412, framed purely as stale-version rejection, with an explicit statement that no other endpoint takes a version field; all 11 calculations are rendered as prose with pinned evaluation/rounding order (fee tiering on the pre-discount gross, per-panelist rounding before averaging, dual conduct variants, buffered half-open pitch conflict vs. closed-interval closure capacity, lottery filter → band → conduct-desc → `created_at` tie-break); every multi-level cascade (approval L1–L3, revocation L1–L4, closure activation L1–L4, complaint-upheld L1–L4, lottery award L1–L3) is spelled out on both branches; the two independent permit axes and the 5-step ops-run ordering are stated.

**Deliberately not in the PRD:** nothing from the scaffold's rule tables was dropped. Omitted by design per the skill: per-endpoint request/response schemas in §4 (readers reconstruct them from §3), trigger conditions in the §5 table, and the scaffold's internal cross-reference notes/`complexity_profile` metadata. The two withheld design files were never opened. One judgement call: the scaffold's `permit_fee_assessment` worked example (22050 full-season vs. 9188 prorated at a month-8 issue) is reproduced in §3.4 since it comes from SCAFFOLD.yaml itself and pins the rounding order.

**Orchestrator verification:** `wc -l PRD.md` = 456; `grep -c '^## ' PRD.md` = 5; `tail` ends at `ERR_SEASON_MINUTE_CAP_EXCEEDED | 409` — no truncation.

## Step 6: Generate Implementation — 2026-08-16T20:34:13.193Z

Implementation complete and verified. Final state:

## Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_2109_busking_permit_program/workspace/implementation/` — Python + Flask, in-memory dicts only (`db.STORES`), **no seeding anywhere** (verified: a fresh boot's `GET /busking/pitches` returns `total_count: 0`).

| Module | Lines | Role |
|---|---|---|
| `start.sh` | 10 | guarded `pip install` + `exec python3 app.py`, `0.0.0.0:$PORT` (default 10000) |
| `app.py` | 48 | app factory, error handlers, 14 blueprints |
| `db.py` | 70 | stores, logical clock (boots at `2026-08-01T00:00:00Z`), id/seq/permit-number mints |
| `errors.py` | 102 | `ApiError` + all 57 error ids → HTTP, per-collection not-found map |
| `gates.py` | 99 | priority constants + ordered gate runner + resolvers |
| `body.py` | 95 | priority-45 well-formedness helpers |
| `utils.py` | 144 | datetimes, half-up rounding, entity/version bookkeeping, pagination |
| `middleware.py` / `response.py` / `listing.py` / `services/serializers.py` | 39/48/27/27 | auth+RBAC, envelope, filtered listings, output |
| `services/calc.py` | 251 | all 11 calculations + constants |
| `services/domain.py` | 279 | cross-entity queries, ledgers, suspension/revocation/mint cascades |
| `routes/*.py` (14 files) | 1 613 | 51 endpoints (route table enumerated: exactly 51, matching PRD §4) |
| **total** | **3 185** | |

## How the 46-rule ordering is enforced

Each handler declares its applicable checks as `(priority, callable)` pairs and passes them to `gates.run_gates()`, which **sorts by priority before executing** — so ordering is a property of `gates.py`, not of the order checks happen to be typed. Priorities are named constants (`P_PATH=30`, `P_BODY_FK=35`, `P_OWNER=40`, `P_BODY=45`, … `P_SEASON_MINUTES=88`), each carrying its PRD §2.6 rank 1–46 in a comment. Auth (1) and role (2) run before the gate set, inside `require_roles`. Verified orderings include auth > existence, role > existence, body-FK > ownership > body-validity, `ERR_COMPLAINT_ALREADY_RESOLVED` (46) > `ERR_INVALID_STATE` (50), `ERR_AUDITION_REQUIRED` (49) > 50, amplification (61) > session-too-long (67), deadline-not-passed (74) > no-entries (83).

## The two OCC rules

Both are required inputs, both compare against the live row's `version`, both 412: `expected_application_version` on `POST /permit-applications/{id}/revisions` (gate 54, after state 50) → `ERR_STALE_APPLICATION_VERSION`; `expected_permit_version` on `POST /session-bookings` (gate 55, after permit-active 51 / suspended 52) → `ERR_STALE_PERMIT_VERSION`. No other endpoint reads a version field.

## Verification

All modules `py_compile` clean and pyflakes-clean. Five smoke suites (≈150 assertions) run against fresh servers, **0 failures**: fee assessment (5400 / 9188 / 4050 / tier-1 boundary 15000→admin 1200), panel scoring (7.00 passes, 4-score mean 7.50), effective cap (78 / 75 when WARNED / 74 amplified / floor 55), warn→suspend→reinstate cascade, closure relocate vs cancel with the two minute ledgers, ops-run five steps, renewal cycle incl. the past-due lapse edge, conduct scoring 87/62/37→BARRED with bar-cascade, prorated refund 2160/11880, lottery ranking + VOID vs `ERR_NO_ELIGIBLE_ENTRIES`, buffered overlap, daily cap, season cap boundary 1800, pagination and all 12 not-found ids. Final check: fresh `bash start.sh` boot answered `POST /busking/zones` with 201 within 3 s.

## Interpretation calls worth flagging

1. `SCAFFOLD_CORNER_DESIGN.yaml`'s lead-time recipe expects `ERR_BOOKING_LEAD_TIME` for a `00:30Z` start in a zone whose quiet window is 23:00–06:00 — but PRD §2.6 puts quiet hours (rank 21) ahead of lead time (rank 26), so the implementation returns `ERR_QUIET_HOURS_VIOLATION` there. PRD ordering was followed; that one corner recipe is self-inconsistent.
2. Entry filing is refused at exactly `entry_deadline_at` (PRD "at or after that instant is refused"), and execute requires strictly past it — the instant itself admits neither.
3. Renewal while `WARNED` → `ERR_INVALID_STATE` (state-machine precondition "compliance_status == CLEAR"); `SUSPENDED` → `ERR_PERMIT_SUSPENDED` at gate 52 as specified.
4. Paying a RENEWAL invoice that already lapsed to PAST_DUE (permit back to `ACTIVE`, `next_season_year` null) credits the money ledger but does not roll the season — the rollover edge is defined only from `RENEWAL_PENDING`.
5. Decision-desk separation of duties is applied to any decision on an application with a PASSED sitting (PRD §2.10 "may not issue that application's decision"), not just approvals.

## Step 5: Generate Unit Tests — 2026-08-16T20:37:25.625Z

Complete. Full coverage of both design indices with zero skips.

## Files written

**`/home/ubuntu/github/CodingPRD/tasks/task_2109_busking_permit_program/test_helpers/`** (1,899 lines)

| File | Lines | Contents |
|---|---|---|
| `types.py` | 433 | 22 enums + entity TypedDicts. `AuditionScore` / `NoiseReading` correctly omit `updated_at` and `version` (PRD §2.4 immutables) |
| `api_client.py` | 214 | 50 endpoint methods over the `/busking` prefix + `/_clock/set_current_utc` |
| `api_errors.py` | 136 | 57 error IDs + HTTP map, registered via `set_error_http_status_map` |
| `assertions.py` | 282 | Per-entity assertions, `assert_standing_matches_conduct_score`, `assert_permit_number_format`, minute/money ledger invariant recomputers, `assert_same_instant` |
| `factories.py` | 205 | Payload factories, input fields only |
| `constants.py` | 64 | Fee tables, conduct/dB/minute thresholds, quoted fee figures |
| `test_users.py` | 50 | `make_performer_headers(performer_id)` for the one `entity_backed` role; opaque builders for the other four, with distinct officer ids for separation of duties |
| `fixtures.py` | 486 | 5 tiers: creations/reads → cascade discovery (`find_permit_for_application`, `first_permit_invoice`) → lifecycle shortcuts (`setup_permit_pending_fee`, `setup_active_permit`, `setup_district_pitch_and_active_permit`, `setup_audition_scheduled`, `setup_audition_passed`) → accumulation (`book_series`, `file_noise_readings`, `uphold_new_complaint`) → closures/epoch |

**`/home/ubuntu/github/CodingPRD/tasks/task_2109_busking_permit_program/test_suite/`** (4,362 lines, 12 modules + conftest) — `test_01_ordinance_map` (9), `test_02_enrollment_and_applications` (11), `test_03_audition_panel` (13), `test_04_fee_assessment_and_payment` (9), `test_05_permit_lifecycle_and_money` (8), `test_06_session_booking_admission` (12), `test_07_minute_ledger_and_concurrency` (6), `test_08_noise_metering` (11), `test_09_complaints_and_conduct` (11), `test_10_rotation_draws` (11), `test_11_closures_and_epoch` (9), `test_12_access_control_and_discovery` (8).

## Coverage

- **118 test functions**, all collecting cleanly under pytest.
- **Queue A: 18/18 difficulty instances**, every one with >=2 tests (36 tests).
- **Queue B: 82/82 non-stub corner instances**, each with >=1 test.
- **8 `excluded_because:` stubs not translated**; all 8 `difficulty_instance` cross-references verified to resolve to a real name in `SCAFFOLD_DIFFICULTY_DESIGN.yaml`.
- **0 instances skipped** — every instance passed the PRD-first two-condition filter.
- 100 distinct `Design:` tags, each exactly one per docstring and always the last line; no untagged, dual-tagged, or orphan tags.
- Every quoted PRD sentence verified by literal grep of `PRD.md` (whitespace-normalized); no `skip`/`skipif`/`xfail`; no "scaffold"/§1.x leakage in generated code.

## Two adjustments worth flagging

1. **`corner_booking_lead_time_and_horizon_enforced`** ships an arithmetically wrong control literal: it asserts a `2026-08-31T10:00:00Z` start returns 201, but from the `2026-08-01T00:00:00Z` clock that is 30 days **and 10 hours** out. PRD §3.6 ("no more than 30 days after it") admits both an instant reading (refuse) and a calendar-date reading (admit), so the literal fails the two-reader test. Both error assertions (`ERR_BOOKING_LEAD_TIME` at 00:30, `ERR_BOOKING_HORIZON_EXCEEDED` at 2026-09-05 — unambiguous under either reading) are kept; the admitted control was moved to `2026-08-25T10:00:00Z`.

2. **Datetime-field equality relaxed to instant equality** (`assert_same_instant`) for `activated_at`, `due_at`, `previous_utc`, `current_utc`. PRD §2.4 mandates three-fractional-digit rendering only for `created_at`/`updated_at`, so a faithful PRD-only implementer could emit `2026-08-01T00:00:00Z` for the others. The instant itself is still asserted exactly.

## Step 7: Run Tests and Iterate — 2026-08-16T20:46:35.654Z

All 8 parallel rounds are green (118/118 each). Exiting with the summary.

## Summary

**Iterations run:** 2 sweeps (baseline + verification). Baseline: 117/118 in all 8 rounds, one deterministic failure. Verification: **118/118 in all 8 rounds, zero union failures, zero flakiness.**

**Tests deleted:** none. The single failure passed both STEP 1a (coverage) and STEP 1b (unique derivability) — PRD §3.6 states the lead-time rule verbatim ("The session must start at least one hour after the current program clock — a `start_at` closer than 60 minutes away is refused with `ERR_BOOKING_LEAD_TIME`"), and it admits only one reading.

**Fixes applied to `test_helpers/`:** none. The offending setup lived in the test function itself, not in a shared fixture, so no other test was affected.

**Fixes applied to `implementation/`:** none. No implementation check was removed, weakened, or added.

**Fix applied to `test_suite/`:**

- `/home/ubuntu/github/CodingPRD/tasks/task_2109_busking_permit_program/test_suite/test_06_session_booking_admission.py` — `test_booking_lead_time_and_horizon_are_both_enforced`, setup only. The test called `setup_district_pitch_and_active_permit()` with no `zone_overrides`, so it inherited the default Riverside Plaza district from `factories.create_zone_payload` (`quiet_hours_start_minute=1380`, `quiet_hours_end_minute=360` — a 23:00–06:00 quiet window). Its sub-hour probe books `2026-08-01T00:30:00Z → 01:30:00Z` off the boot clock of `2026-08-01T00:00:00Z`, an interval lying **entirely inside** that quiet window. PRD §2.6 ranks the quiet-window check at 21 and the lead-time check at 26, and states "no later check may mask an earlier one, and no earlier check may be skipped because a later one would also fail" — so the PRD-faithful answer is `ERR_QUIET_HOURS_VIOLATION`, exactly what the server returned. This was a STEP 2 test bug: the setup did not express the rule the docstring claims. The district is now registered with `quiet_hours_start_minute=0, quiet_hours_end_minute=0`, which PRD §3.1 defines as "the district has no quiet window whatsoever and nothing is ever refused on quiet-hours grounds there", so rule 26 is now actually reached. All three assertions were kept at full strength — `ERR_BOOKING_LEAD_TIME`, `ERR_BOOKING_HORIZON_EXCEEDED`, and the 201 control with `season_minutes_used == 60`. The same no-quiet-window district idiom already had precedent in this file (the "Longhaul Quay" season-cap test).

**Notes on the two generation-step hints:**

- The corner-recipe conflict flagged by the implementation generator (`ERR_BOOKING_LEAD_TIME` vs `ERR_QUIET_HOURS_VIOLATION` at 00:30Z) was real and was precisely this failure. The implementation's reading of PRD §2.6 is correct; the resolution belonged in the test's district setup, not in the precedence table.
- The test generator's booking-horizon adjustment (`2026-08-31T10:00:00Z` → `2026-08-25T10:00:00Z`) is sound and needed no change — 2026-08-31T10:00Z is 30 days *and 10 hours* past the boot clock and so is ambiguous under PRD §3.6's "no more than 30 days after it"; 2026-08-25 is unambiguously inside the horizon and now returns 201.

**Orchestrator verification:** all 8 `results.{1..8}.json` re-read independently — each reports `passed=118 / total=118 / failed=0`.

## Step 8: Finalize PRD — 2026-08-16T20:49:23.771Z

Done. `PRD_FINALIZED.md` created with a single edit.

**Line counts:** PRD.md 456 lines → PRD_FINALIZED.md 456 lines (0 line delta; one line rewritten in place, +517 chars ≈ +0.6% of the file's 84.5 KB). 1 of 456 lines changed = 0.22% line delta.

**Change:**
- §3.6 (Occupying a Pitch) — insert — appended one sentence pinning the lead-time and booking-horizon bounds as elapsed-time (instant-arithmetic) comparisons against the program clock, with both edges inclusive: `start_at` exactly 60 minutes out passes lead time, exactly 30 days (720 h) out passes the horizon, anything strictly later is refused — `implementation/routes/bookings.py:92` and `:96` (constants at `implementation/services/calc.py:51-52`).

**Pre-edit search log (the one edit):**
- (a) Subject: the two clock-relative bounds on a session booking's `start_at` — `ERR_BOOKING_LEAD_TIME` and `ERR_BOOKING_HORIZON_EXCEEDED` — and specifically whether "no more than 30 days after it" is a duration or a calendar-date difference.
- (b) Impl paths enumerated: grepped `MIN_BOOKING_LEAD_MINUTES` / `MAX_BOOKING_HORIZON_DAYS` repo-wide — only definitions at `services/calc.py:51-52` and the two uses at `routes/bookings.py:92,96`; grepped every `db.now()` callsite (invoices, permits, lottery entry/execute, auditions, applications, complaints, ops, `routes/bookings.py:205` cancel-before-start, `services/domain.py`) to confirm no other endpoint applies a lead-time or horizon window; enumerated every booking-creation site (`routes/bookings.py:141` direct, `services/domain.py:243` lottery award) and the closure relocation path (`routes/closures.py:138-144`, which re-pitches an existing booking and never re-checks either bound); read `gates.py:63-69` to confirm precedence ranks 21/26/27 already match §2.6 verbatim; read `calc.violates_quiet_window` (equal quiet minutes ⇒ no window) against §3.1/§3.6, which already state that rule verbatim.
- (c) Wording adjustment: kept the new sentence anchored to "the lead-time check"/"the horizon check" of the preceding direct-booking sentence rather than making any universal claim about session bookings, precisely because lottery-minted bookings (`services/domain.py:243`) and closure relocations never apply these two bounds. Also avoided "calendar day"/"UTC date" phrasing so as not to collide with the genuinely date-based rules elsewhere in §3.6 (daily session cap, `domain.daily_session_count`).

**Items deliberately not patched:** the Step 7 test-setup fix (quiet window 0/0) is a pure fixture bug — PRD §3.1 already says equal quiet-hour minutes mean no quiet window and nothing is ever refused on quiet-hours grounds there; PRD §2.6 already ranks quiet hours (21) ahead of lead time (26) with the explicit no-masking clause; and the lead-time rule itself is already stated verbatim and uniquely. No implementation fixes and no test deletions existed to trace.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (269), an in-place append to the §3.6 booking-window paragraph. No sections added or removed.

## Step 9: Complete PRD — 2026-08-16T21:00:23.552Z

Verified on disk: 456 lines (same as source), 5 `## ` sections, error catalogue ends correctly at `ERR_SEASON_MINUTE_CAP_EXCEEDED`.

## Summary

**Files** — `PRD_FINALIZED.md` 456 lines / 84,856 chars → `PRD_COMPLETED.md` 456 lines / 91,709 chars (**+6,853 chars**, 31 lines touched, no new sections/paragraphs; every change is an in-paragraph insert or revision).

**Counts** — 34 changes: **31 ambiguity-pins**, **3 mismatch-revisions**.

### Changes

- §2.2 Success Response — insert — ambiguity — `api_request_timestamp` reads the program clock, not host time — `response.py:20`
- §2.3 Pagination — revise — **mismatch** — `limit`/`offset` bounds are enforced by clamping, and unparseable values fall back to defaults; no pagination arg ever errors — `utils.py:123-133`
- §2.4 Timestamps — insert — ambiguity — only `created_at`/`updated_at` always carry 3 fractional digits; every other instant renders at second resolution unless it holds sub-second precision — `utils.py:27-42`, `services/serializers.py:17-21`
- §2.6 rule 4 — insert — ambiguity — absent/`null` FK keys defer to step 6; any other value (incl. non-string) resolves here and 404s — `gates.py:86-94`, `db.py:63-66`
- §2.6 rule 9 — revise — **mismatch** — the `ERR_AUDITION_REQUIRED` gate fires from *any* state other than `AUDITION_PASSED`, not only audition-branch states — `routes/applications.py:234-239`
- §2.6 well-formedness — insert — ambiguity — declared JSON types enforced; optional strings must also be non-empty; instants normalised from any offset; explicit `null` on an optional field = omitted — `body.py:16-93`, `utils.py:9-24`
- §2.11 Listings — insert — ambiguity — filters compare stringified field values, a null field never matches, unknown query params ignored, and **no listing is ownership-scoped** for `Performer` callers — `listing.py:8-17`
- §3.1 Districts — revise — ambiguity — `evening_start_minute` is required; `max_concurrent_closures` may not be below 1 — `routes/zones.py:28,32`
- §3.1 Districts — insert — ambiguity — exact required/optional split of the zone payload; `name` has no length ceiling — `routes/zones.py:23-34`
- §3.1 Quiet window — insert — ambiguity — an occupation covers every clock minute it touches (start minute through the minute of the last instant before `end_at`) — `services/calc.py:196-216`
- §3.1 Pitches — revise — ambiguity — `premium_slots_per_draw` may not be below 1 — `routes/pitches.py:39`
- §3.2 Performers — insert — ambiguity — no syntactic email validation; stored verbatim, case-folded only for the uniqueness test — `routes/performers.py:27,37-38`
- §3.2 Change request — insert — ambiguity — a `CHANGES_REQUESTED` decision leaves `decided_by_user_id`/`decided_at` null — `routes/applications.py:275-277`
- §3.3 Scheduling — revise — ambiguity — sitting starts with `finalized_by_user_id`/`finalized_at` null; `scheduled_for` unconstrained vs the clock; both scheduling refusals are `ERR_INVALID_STATE` — `routes/auditions.py:34-56`
- §3.3 Panel scores — insert — ambiguity — no state gate on score filing (admitted on `PASSED`/`FAILED`/`CANCELLED` sittings); sitting `version` moves per filing — `routes/auditions.py:93-110`
- §3.4 Decision — insert — ambiguity — a `decision_note` on the approve/reject branches is validated then discarded — `routes/applications.py:230-232,278-287`
- §3.4 Approval gate — revise — **mismatch** — same broadening as §2.6 rule 9, with the extra states enumerated — `routes/applications.py:234-239`
- §3.5 Payment — insert — ambiguity — the call answers with the settled invoice, not the permit — `routes/invoices.py:72`
- §3.5 Renewal — revise — ambiguity — a non-`ACTIVE` permit and a merely `WARNED` one are both `ERR_INVALID_STATE`; only `SUSPENDED` yields `ERR_PERMIT_SUSPENDED` — `routes/permits.py:226-235`
- §3.5 Revocation — revise — ambiguity — `reason` is required, non-empty, and never persisted — `routes/permits.py:284`
- §3.5 Renewal payment — insert — ambiguity — `permit_number`, `activated_at` and the compliance axis survive the rollover; `net_fees_paid_cents` accumulates across seasons — `routes/invoices.py:56-71`
- §3.6 Cancellation — revise — ambiguity — the optional `reason` is validated but never persisted — `routes/bookings.py:269-270`
- §3.7 Ranking — insert — ambiguity — `priority_band` is fixed from the pre-run `premium_wins_this_season` for every candidate — `routes/lottery.py:234-241`
- §3.7 Awarding — revise — ambiguity — filtered-out entries are never banded and keep `priority_band` null — `routes/lottery.py:257-261`
- §3.7 VOID branch — revise — ambiguity — voided entries keep both `rank_position` and `priority_band` null — `routes/lottery.py:223-232`
- §3.7 Win cascade — insert — ambiguity — minted booking's `duration_minutes`/`noise_violation_count`/`relocated_from_pitch_id`/`effective_noise_cap_db`, and **no** admission gate (quiet, availability, ceiling, overlap, daily cap) is re-run — `services/domain.py:238-260`
- §3.8 Readings — insert — ambiguity — no state gate on the metered session; a `COMPLIANT` reading mutates nothing and bumps no `version` — `routes/readings.py:35-79`
- §3.8 Adjudication — revise — ambiguity — `resolution_note` validated but never persisted — `routes/complaints.py:224`
- §3.8 Rescoring — revise — ambiguity — `upheld_complaint_count` is recomputed (not nudged), and the performer's `version` moves only when one of the four fields actually changes — `services/domain.py:164-185`
- §3.8 Reinstatement — revise — ambiguity — `note` validated but never persisted — `routes/permits.py:307-308`
- §3.9 Activation — insert — ambiguity — an already-`CLOSED` pitch is untouched (no `version` bump); the district row is versioned on every activation — `routes/closures.py:116-127`
- §3.9 Relocation — revise — ambiguity — the recomputed cap is evaluated at the session's own `start_at` against the permit's compliance axis at relocation time — `routes/closures.py:150`, `services/domain.py:112-117`
- §3.9 Epoch — insert — ambiguity — each of the five steps walks its rows in `created_at` ascending order — `routes/ops.py:183,206,224,246,260`
- §3.9 Epoch report — insert — ambiguity — `performers_rescored_count` counts every performer examined (`upheld_complaint_count > 0`), changed or not — `routes/ops.py:257-265`

### Notes
- Two PRD statements were left alone because they are unobservable rather than mismatched: the fallback-pitch *self-reference* clause in §3.1 (a client cannot supply the not-yet-minted pitch's id, so `routes/pitches.py:49-55` checks only the zone), and the §3.4 claim that only rejection-from-`AUDITION_SCHEDULED`/`UNDER_REVIEW` cancels a live sitting (impl cancels `SCHEDULED` sittings on every rejection path, which is behaviourally identical since the other source states cannot carry one).
- Tests were used only as a sanity cross-reference; every pin above is derived from `implementation/` source.

**Orchestrator verification:** `PRD_COMPLETED.md` = 456 lines, `grep -c '^## '` = 5, tail ends at `ERR_SEASON_MINUTE_CAP_EXCEEDED | 409`; `diff PRD_FINALIZED.md PRD_COMPLETED.md` = 31 changed lines, no section added or removed.
