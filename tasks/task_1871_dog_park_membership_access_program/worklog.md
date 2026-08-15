# Worklog — task_1871_dog_park_membership_access_program

## Step 1: Create Task Directory — 2026-08-14T21:54:00.000Z

Directory tasks/task_1871_dog_park_membership_access_program/ and tasks/task_1871_dog_park_membership_access_program/workspace/ pre-created by the invoking pipeline (Step 1 done externally).

## Step 2: Generate Scaffold — 2026-08-14T22:19:00.000Z

All three scaffold artifacts are generated and clean. Summary:

**Files written** (under `/home/ubuntu/github/CodingPRD/tasks/task_1871_dog_park_membership_access_program/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (response envelope, entities, state machines, concurrency rules, calculations, validations, endpoints, errors, RBAC); no difficulty/corner keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single `scaffold_difficulty_design:` key, 18 instances (9 rules × 2)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single `scaffold_corner_design:` key, 67 instances (58 active + 9 `excluded_because:` stubs) across all 9 claim-extraction-guide sections

**Scaffold surface counts:** 9 entities (Member, Dog, Membership, GuestPass, ParkArea, AreaClosure, ParkVisit, IncidentReport, WasteStation), 36 endpoints, 34 error codes, 8 state machines, 8 calculation rules, 12 ordered validation rows, 2 OCC concurrency rules, 4 roles (Anonymous opaque, Member + Steward entity-backed by Member, ParkAdmin opaque). Archetype: quota/allocation + compliance/audit; flat topology; cyclic state machines; hierarchical-override roles.

**Difficulty design highlights:** dual-variant fees (early 13500 vs lapsed 17500 renewal) vs provisional/confirmed strike scoring (35 vs 20); rounding-order pin (per-line 2506 vs sum-first 2507) vs peak-window capacity collapse (2→1); Member suspension cycle + Dog resubmission cycle; depth-4 incident-confirm cascade + depth-2 nightly-run expiry cascade; state-beats-constraint and safety-beats-capacity priority pairs; capacity-==2 and strike-==30 boundaries; closure half-open adjacency vs dog open-visit unbounded overlap; occupancy check-in/check-out and guest-pass purchase/void conservation invariants.

**Verification:** `scaffold_lint.py` verdict — clean lint (534 calls scanned, 0 violations). Mechanical self-checks additionally passed: no forbidden race vocabulary, file split honored, 85 unique instance names, full `${var}` placeholder closure, all stubs resolve to real difficulty instances, and every pinned numeric literal was computed and verified (including weekday fixtures: 2026-08-01 = Saturday, 2026-08-03 = Monday).

One mid-course fix worth noting: the lint's FK reverse-reachability check requires sub-resource GET paths to use the literal `{id}` parent segment, so nested paths were normalized to `/dog-park/members/{id}/dogs` etc., and `area_id?` was added to the incident-report filtered list.

## Step 3: Copy Shared Files — 2026-08-14T22:20:00.000Z

Copied ./INSTRUCTION.md to tasks/task_1871_dog_park_membership_access_program/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-14T22:31:00.000Z

PRD generation complete. The two forbidden design-index files were never opened or consulted.

## Summary

**File written:** `/home/ubuntu/github/CodingPRD/tasks/task_1871_dog_park_membership_access_program/workspace/PRD.md` — 296 lines.

**Section list:**
- §1 Introduction (2 paragraphs: business context + design commitments, API mount `/dog-park`)
- §2 Global Specifications — 2.1 RBAC (4 roles with identity prose per role), 2.2 API Response Structure (verbatim block, byte-identical to source), 2.3 Pagination, 2.4 Logical Clock & Calendar Semantics (startup default 2026-08-01T00:00:00Z), 2.5 Common Resource Properties, 2.6 OCC (both rules with paths, `expected_member_version`/`expected_membership_version`, `ERR_STALE_VERSION` 412), 2.7 Validation Order (12-stage priority pipeline), 2.8 Nested Resource Retrieval, 2.9 Precision & Rounding, 2.10 Cascading Consistency & Atomic Side Effects
- §3 Business Logic — 3.1 Enrollment/Profiles/Stewards, 3.2 Dog Verification, 3.3 Membership Purchase & Renewal (proration + both renewal variants), 3.4 Areas/Peak Windows/Closures, 3.5 Gate Check-in/out, 3.6 Guest Passes & Monthly Allotment, 3.7 Incidents/Strikes/Suspension, 3.8 Waste Stations & Nightly Run (pinned 6-step epoch, 8 tally fields)
- §4 Endpoint Definitions — 36 rows, 4 columns (status-code paragraph notes 201 for creations incl. nightly epoch, 200 for modifications incl. clock-set)
- §5 Error Code Catalogue — 34 rows, 2 columns (statuses taken from the per-error catalog, e.g. `ERR_SELF_REPORT_NOT_ALLOWED` 422)

**Coverage-audit notes (Hard Contracts):**
- Contract 1 (Field-Name Coverage): 51/51 entity+common fields, 16/16 endpoint input/query/output identifiers, 10/10 path params present verbatim in backticks — **PASS**. (First audit run produced false negatives because fenced JSON blocks broke token pairing; re-ran with fences stripped.)
- Contract 2 (Rule Coverage): 12 validation priorities expressed as an ordered pipeline plus renewal-specific ordering (OCC first, member-state before membership-state, quota last); 2/2 OCC rules with endpoint+field+error+status; all 33 state transitions across 8 state machines with preconditions and side effects; 8/8 calculations as precise prose with boundary readings (capacity ==rejects/==−1 admits; exactly-30 suspends; 75 OK vs 100 flags; count 2 rejects/1 admits; per-line round-then-sum pinned); 34/34 error ids matchable in §2/§3 prose; sibling symmetry held (early/lapsed renewal, CONFIRMED/DISMISSED, REJECTED/EXPIRED resubmit, weekday/weekend pricing, two force-close paths) — **PASS**
- Contract 3 (§3 Path Purity): 321 backtick tokens scanned, 0 slash-tokens, 0 bare HTTP methods, 0 method+path combos — **PASS**
- §2.2 verified byte-identical to `section-2.2-response-structure.md`; all 31 state/enum values present as exact strings. PRD.md ends at §5 with no audit footer.

## Step 5: Generate Unit Tests — 2026-08-14T22:55:00.000Z

Generation complete for task_1871 (Dog Park Membership & Access Program).

## Files written

**`test_helpers/`** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1871_dog_park_membership_access_program/test_helpers/`):
- `types.py` — 9 entity TypedDicts + 11 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with all 36 `/dog-park` endpoints
- `api_errors.py` — 34 `ApiErrorId` values + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + `assert_instant_equals` (format-tolerant UTC-instant comparison)
- `factories.py` — payload builders for every write endpoint (input fields only)
- `constants.py` — fee/strike/fill/quota constants and pinned fee values (6288/2506/13500/17500/14500)
- `test_users.py` — `TEST_USERS` + per-instance `make_member_headers` / `make_steward_headers` (both entity_backed:Member)
- `fixtures.py` — composite helpers: `setup_active_member`, `setup_area_with_members`, `check_in_dog/guest`, `visit_in_out`, `purchase_pass`, `file_report`/`confirm_report`/`suspend_member_via_report`, `create_steward`, `run_nightly`
- `__init__.py` — barrel export

**`test_suite/`**: `conftest.py` + 8 domain-named files (`test_01_member_registration_and_profiles` … `test_08_waste_stations_and_nightly_run`).

## Test counts

- **Queue A (Difficulty): 34 tests** — 17 of 18 instances × 2 tests each.
- **Queue B (Corner): 58 tests** — every non-stub instance × 1 test. All 9 `excluded_because:` stubs were left untranslated; every stub's `difficulty_instance` cross-reference resolves.
- **Total: 92 tests** (pytest collection: 92 collected, 0 errors).

## Skipped instances (PRD-first filter)

- `Difficulty/priority_pair_validation_conflict/checkin_state_beats_size_mismatch` — **skipped**: the PRD never states that check-in requires an ACTIVE member. `ERR_MEMBER_NOT_ACTIVE` trigger conditions appear only for renewal (§3.3) and guest-pass purchase (§3.6); §3.5's gate enumeration covers ownership, dog verification, vaccination, size, double-visit, closure, and capacity — no member-status gate. Two PRD-only readers could legitimately diverge (one rejecting suspended members at the gate, one admitting them), so both the trigger and the asserted priority outcome fail coverage/unique-derivability. Not weakened, not placeholder-marked; the gap stays a gap.

## Stage 2 self-check results

- All modules compile (`py_compile`) and import; pytest collects 92 tests cleanly.
- Tag audit: 92/92 tests carry exactly one `Design:` line; 0 unresolved tags; every translated difficulty instance has ≥2 tests (except the skip above); every non-stub corner instance has ≥1 test; no stub has a test; all 9 stub cross-references resolve.
- Citation audit: 155/155 quoted docstring passages grep verbatim against `workspace/PRD.md` (whitespace-normalized); no endpoint-titular-only citations.
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no "scaffold" references in generated code.

Notable adjudications: version assertions use exact equality only where PRD pins the value (creation=1, OCC patch/renew increments) and lower-bound comparisons in cascades (§2.5's "derived-field recomputations" makes exact mid-cascade member versions non-unique); instant comparisons (`term_start`, `term_end`, `last_serviced_at`) use parsed-instant equality since PRD pins the instant but not fractional-digit rendering.

## Step 6: Generate Implementation — 2026-08-14T22:55:00.000Z

Complete Flask implementation for task_1871 (Dog Park Membership & Access) written to `/home/ubuntu/github/CodingPRD/tasks/task_1871_dog_park_membership_access_program/workspace/implementation/`.

**Files written (20):**
- `start.sh` — executable launcher; guards `pip install` behind `python3 -c "import flask"` (no-op once deps present, safe for per-test reboots), then `exec python3 app.py` in the foreground
- `requirements.txt` — `flask>=2.0`
- `app.py` — Flask entry, `ApiError` handler, blueprint registration; binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory `store` (9 dicts keyed by id, insertion seq, logical clock starting exactly `2026-08-01T00:00:00Z`, nightly-run watermark). No seeding, no disk persistence
- `errors.py` — all 34 error IDs with catalog HTTP statuses + `ApiError`
- `response.py` — exact scaffold envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields inside `meta`; error body `{error_id, message}`)
- `middleware.py` — auth stages 1–3 (`X-User-ID`/`X-User-Role` header check → role listing → steward flag gate)
- `helpers.py` — logical-clock formatting (3-fractional-digit ISO), strict date/datetime parsing, request-shape validators, `limit`/`offset` pagination (default 10/0, bounds 1–100/≥0) sorted by `created_at` asc
- `routes/` — one module per resource: `clock`, `members`, `dogs`, `memberships`, `guest_passes`, `areas`, `closures`, `visits`, `incidents`, `waste_stations`, `service_runs` (all 36 endpoints)
- `services/domain.py` — fee math (per-line `Decimal` ROUND_HALF_UP: initial proration, early 10%-off, lapsed +2500 reinstatement), strike scoring with suspension cascade, occupancy/effective-capacity, guest monthly usage, suspension cascade, six-step nightly epoch

**Key behaviors verified by smoke tests against `bash start.sh`:**
- Boot + serve confirmed on a fresh process; reboot wipes all state (member → 404, 0 areas, clock back to default)
- Fee math: initial 2-dog fee 6288 (5030 + 1258 per-line rounding), early renewal 13500 with term extended to 2027, lapsed renewal 14500 with member reactivation
- Pipeline order: `ERR_NO_VERIFIED_DOG`, stale-version 412 on PATCH/renew before state checks, ownership 403, steward gate 403, self-report 422
- Peak-window derating (eff_cap 1 during window), capacity boundary, `ERR_AREA_CLOSED` under ACTIVE closure, closure overlap/adjacency
- Guest pass fees 1500/2250 (weekday/Saturday), monthly limit 2, void refunds allotment, nightly expiry of ISSUED passes
- Incident pipeline: FILED→UNDER_REVIEW by steward, steward CONFIRMED→403, CONFIRMED at 30 strikes → full suspension cascade (member/membership SUSPENDED, visits FORCE_CLOSED, passes VOID), reinstate resets strikes and reactivates
- Nightly epoch tallies correct, including waste-fill boundary (3 visits → 75 OK, 4th → 100 NEEDS_SERVICE). One fix applied during testing: the "visits since previous run/creation" baseline uses a `(logical time, insertion seq)` watermark so a frozen logical clock can't make check-ins invisible or double-counted.

## Step 7: Run Tests and Iterate — 2026-08-14T23:00:31.000Z

Clean 8-round parallel sweep achieved. Final summary:

## Summary

- **Iterations run**: 2 (initial sweep → 1 fix → verification sweep; final sweep: all 8 rounds × 92/92 passed, 0 failed).

- **Tests deleted**: none.

- **Fixes applied to `test_helpers/`**: none.

- **Fixes applied to `implementation/`**: none.

- **Fixes applied to `test_suite/`**: 1
  - `/home/ubuntu/github/CodingPRD/tasks/task_1871_dog_park_membership_access_program/test_suite/test_03_membership_fees_and_renewal.py` — `TestRenewalFlavors.test_early_vs_lapsed_renewal_fee_lifecycle` (STEP 2, test-setup bug). The test asserted the lapsed-renewal fee `17500 = 12000 + 3000×1 + 2500` (PRD §3.3: "12000 cents plus 3000 cents for each verified dog beyond the first, plus a flat 2500-cent reinstatement fee"), which requires 2 VERIFIED dogs at renewal time. Its setup used the fixture default `vaccination_expires_on="2027-06-01"`, then advanced the logical clock to 2028-01-15 and ran the nightly epoch — which per PRD §3.8 stage 6 correctly swept both dogs VERIFIED → EXPIRED, leaving 0 verified dogs. The implementation's 14500 was the PRD-faithful result for the state the test actually constructed (SCAFFOLD also pins `input_set: Dogs with verification_status == VERIFIED at renewal time`). Fix: the test's `setup_active_member` call now passes `vaccination_expires_on="2029-06-01"` so both dogs remain VERIFIED through the 2028-01-15 run, making the setup match the intended 2-verified-dog scenario. Assertion unchanged; no implementation check weakened.

- **Key findings**: The failure was fully deterministic (8/8 rounds, identical `assert 14500 == 17500`), not flaky. No implementation defects found — the adjudication pipeline, OCC ordering, fee rounding, cascades, and nightly epoch all behaved per PRD. No PRD-silence or unique-derivability deletions were warranted: every one of the 92 tests traces to verbatim PRD prose.

## Step 8: Finalize PRD — 2026-08-14T23:03:38.000Z

PRD_FINALIZED.md is complete. Summary below.

## Line counts and %-delta
- PRD.md: 296 lines; PRD_FINALIZED.md: 296 lines; 0% line-count delta. Exactly one line modified in place (line 157, §3.3) — one sentence inserted.

## Changes
- **§3.3 (Membership Purchase, Proration, and Renewal)** — **insert** — appended "For both flavors, the per-dog line takes the count of the member's dogs in `VERIFIED` status at renewal time." to the closing renewal paragraph — impl: `/home/ubuntu/github/CodingPRD/tasks/task_1871_dog_park_membership_access_program/workspace/implementation/services/domain.py:69-73` (`verified_dog_count` counts `verification_status == "VERIFIED"` at call time), invoked inside the renew request at `/home/ubuntu/github/CodingPRD/tasks/task_1871_dog_park_membership_access_program/workspace/implementation/routes/memberships.py:88` (early) and `:96` (lapsed) via `domain.py:163` and `domain.py:172`.

## Why only one edit
The step_7_diff lists exactly one item — a test-setup fixture bug (test_suite-only fix; zero implementation fixes, zero deletions, zero helper fixes). Its failure mode (`14500` vs `17500`) hinged entirely on whether the renewal per-dog fee counts VERIFIED dogs **at renewal time**. The PRD pinned the evaluation moment explicitly for purchase ("at purchase time") but left it unstated for both renewal flavors; the implementation pins it by evaluating `verified_dog_count` synchronously inside the renew request. The inserted sentence removes exactly that asymmetry and nothing else. No other PRD silence or mismatch was revealed, so no further edits were warranted.

## Pre-edit search log (single edit)
- **(a) Subject**: the per-dog fee line's VERIFIED-dog count for both renewal flavors — specifically the moment the count is evaluated.
- **(b) Impl paths enumerated and read/grepped** (via full read of `routes/memberships.py`, read of `services/domain.py:60-190`, and repo-wide grep for `verified_dog_count`/`verification_status`):
  - `services/domain.py:69-73` — count definition (request-time, VERIFIED-only)
  - `routes/memberships.py:34` — purchase gate (purchase path; untouched by edit)
  - `services/domain.py:146-156` — `initial_membership_fee` (PRD already pins "at purchase time"; untouched)
  - `services/domain.py:159-167` + `routes/memberships.py:88` — early renewal, count at renewal time (consistent)
  - `services/domain.py:170-175` + `routes/memberships.py:96` — lapsed renewal, count at renewal time (consistent)
  - `services/domain.py:302-307` — epoch stage 6 VERIFIED→EXPIRED sweep (edit makes no claim about when dogs leave VERIFIED; §3.8 prose unchanged)
  - `routes/visits.py:58`, `routes/dogs.py:92-129` — check-in gate and status transitions (not fee paths; untouched)
- **(c) Wording adjustment**: trimmed an initial draft that also restated the "subtract one, floored at zero" mechanics — the bullets' existing "beyond the first" already matches impl's `max(0, count-1)`, so the edit pins only the temporal qualifier. Placement moved to the closing "Both flavors..." paragraph (rather than between the colon lead-in and bullets) to keep the colon's referent intact, and reused the section's own idiom "at renewal time" (already used in both bullets), mirroring the purchase paragraph's "at purchase time".

## Step 9: Complete PRD — 2026-08-14T23:13:42.000Z

Done. PRD_COMPLETED.md is written and verified: line count unchanged (296 → 296), all edits are in-paragraph inserts/revisions, no new sections.

## Summary

**Source vs output:** `workspace/PRD_FINALIZED.md` (296 lines, 41,813 chars) → `workspace/PRD_COMPLETED.md` (296 lines, 46,594 chars). Char-delta **+4,781**; 22 paragraph-lines modified in place, 0 lines added or removed.

**Counts:** 25 changes total — **23 ambiguity-pins**, **2 mismatch-revisions**.

### Changes (section — insert|revise — class — what — impl ref)

1. §2.1 — revise — ambiguity — steward-role request whose `X-User-ID` matches no persisted member also fails with `ERR_NOT_A_STEWARD` — middleware.py:36-42
2. §2.3 — revise — ambiguity — `limit`/`offset` must parse as integers; offset minimum 0; non-integers → `ERR_INVALID_REQUEST` — helpers.py:128-147
3. §2.3 — insert — ambiguity — `created_at` ties broken by creation (insertion) order — helpers.py:150-153
4. §2.4 — insert — ambiguity — clock may be set to any instant (backward allowed, no monotonicity check); all server-emitted timestamps (envelope, `created_at`/`updated_at`, check-in/out, `last_serviced_at`) read the logical clock; instant inputs must carry a timezone designator else `ERR_INVALID_REQUEST` — routes/clock.py:17-23, response.py:15-19, helpers.py:39-52
5. §2.7 stage 4 — insert — ambiguity — entity-bound ownership is evaluated immediately after the entity's existence check (nonexistent entity → 404, never `ERR_NOT_OWNER`); path-`memberId` ownership is a pure comparison firing at stage 4 — routes/dogs.py:76-78, members.py:57-59, visits.py:132-134, guest_passes.py:90-92
6. §2.7 stage 5 — insert — ambiguity — required strings must be non-empty; undocumented body fields ignored; unparseable/unknown-enum list-filter values → `ERR_INVALID_REQUEST` — helpers.py:82-97, guest_passes.py:63-69, visits.py:148-150, incidents.py:74-76
7. §2.7 stage 6 — insert — ambiguity — body-referenced identifiers validated in narrative order (check-in: area → dog/pass; incident filing: subject member → dog → area) — routes/visits.py:42-52, incidents.py:41-48
8. §3.1 — revise — ambiguity — duplicate email at registration or profile update → `ERR_INVALID_REQUEST`; non-string non-null `phone` → `ERR_INVALID_REQUEST` — routes/members.py:38-41, 73-76
9. §3.2 — insert — ambiguity — malformed `vaccination_expires_on` → `ERR_INVALID_REQUEST` at registration and resubmission — routes/dogs.py:45-47, 112-116
10. §3.2 — insert — ambiguity — verify `reason` is optional/nullable, stored verbatim on rejection, ignored on approval — routes/dogs.py:87-89, 100-103
11. §3.3 — insert — ambiguity — purchase admits a member in any status; only `PENDING_VERIFICATION` flips to `ACTIVE`; repeat purchase mints a fresh `ACTIVE` membership with `renewal_count` 0 — routes/memberships.py:33-50
12. §3.3 — revise — **mismatch** — "lists and reads their own memberships" → lists only; no single-membership read endpoint exists in §4 or impl — routes/memberships.py (list route only)
13. §3.3 — revise — ambiguity — renewing a membership in any other status (e.g. `SUSPENDED`) → `ERR_MEMBER_NOT_ACTIVE` — routes/memberships.py:102-106
14. §3.4 — revise — ambiguity — `capacity` integer > 0; `peak_capacity` integer 0..`capacity` inclusive; peak-window minutes integers with 0 ≤ start < end ≤ 1440; explicit null `peak_windows` → [] — routes/areas.py:21-58
15. §3.4 — insert — ambiguity — a closure window lying entirely in the past is accepted and, never activating, remains `SCHEDULED` — routes/closures.py:26-49, services/domain.py:263-272
16. §3.5 — revise — ambiguity — a `ParkAdmin` check-in binds visit `member_id` to the dog's owner / pass's sponsor, not the opaque admin id — routes/visits.py:74, 91
17. §3.6 — revise — ambiguity — `valid_on` unconstrained at purchase (past/present/future accepted; malformed → `ERR_INVALID_REQUEST`); sponsor `X-User-ID` matching no member → `ERR_MEMBER_NOT_FOUND` — routes/guest_passes.py:27-37
18. §3.7 — revise — **mismatch** — `strike_points` is a running total incremented at each confirmation, so reinstatement's zeroing means previously `CONFIRMED` reports never re-enter the total (replaces "sums across `CONFIRMED` reports") — routes/incidents.py:142, members.py:101
19. §3.7 — revise — ambiguity — advance `to` admits exactly `UNDER_REVIEW`/`CONFIRMED`/`DISMISSED`; any other value → `ERR_INVALID_REQUEST` — routes/incidents.py:21, 109
20. §3.7 — insert — ambiguity — `FILED → UNDER_REVIEW` leaves the provisional score unchanged, does not mutate the subject member record, and accepts but does not record `resolution_note` — routes/incidents.py:123-130
21. §3.7 — insert — ambiguity — steward attempting `CONFIRMED`/`DISMISSED` is rejected at the authorization stage, before report existence/state — routes/incidents.py:114-118
22. §3.7 — revise — ambiguity — suspension cascade fires only when the subject member stands `ACTIVE` at confirmation; `LAPSED`/already-`SUSPENDED` subjects accrue points without cascade — routes/incidents.py:139-145
23. §3.7 — revise — ambiguity — suspension flips *every* `ACTIVE` membership of the member to `SUSPENDED` — services/domain.py:194-197
24. §3.7 — revise — ambiguity — reinstatement consults the most recently created membership; no membership or other-status latest → member returns `ACTIVE` with no membership mutated — routes/members.py:102-115
25. §3.8 — insert — ambiguity — nightly stage 2 leaves a member already non-`ACTIVE` (e.g. `LAPSED` behind a fresh `ACTIVE` membership) untouched — services/domain.py:246-251

**Not changed:** everything the PRD already pinned uniquely was verified against impl (fee formulas per-line half-up rounding, weekend pass pricing 2250/1500, strike threshold 30 inclusive, stage-11 closure-before-`valid_on` order, quota-last adjudication, nightly six-stage order, tally field names, 201/200 status mapping, envelope shapes) — no discrepancies found in those passages.
