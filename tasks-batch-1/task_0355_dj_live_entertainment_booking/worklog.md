# Worklog — task_0355_dj_live_entertainment_booking

## Step 1: Create Task Directory — 2026-06-14T13:09:33.000Z

Created `tasks/task_0355_dj_live_entertainment_booking/` and `tasks/task_0355_dj_live_entertainment_booking/workspace/` (pre-allocated folder, no auto-increment scan). Difficulty: Expert (passed to Step 2 scaffold-generator only).

## Step 2: Generate Scaffold (Expert tier) — 2026-06-14T13:28:24.000Z

Clean lint, all 21 errors now referenced by a validation or concurrency rule, all three files parse. The scaffold is complete.

Generated the complete Expert-tier scaffold for **task_0355_dj_live_entertainment_booking** — three files, all passing `scaffold_lint.py` (`VERDICT: clean lint`, 576 setup/trigger calls scanned).

**Complexity profile**: primary archetype `temporal_windowing` + secondary `workflow_orchestration`; layers `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `rate_threshold_triggers`; `flat` topology; `cyclic` state-machine shape; `peer_roles`; `immediate` consistency.

**SCAFFOLD.yaml** (§1.0–§1.7):
- **11 entities**: Performer, TravelZone, PackageOffering, EquipmentItem, Booking, Client, PaymentRecord, SongRequest, ContractDocument, BackupAssignment, BlackoutWindow (13 FKs, all with reverse-reachability GETs).
- **5 state machines**: Booking (9-state cyclic with negotiation loop CONTRACT_SENT↔NEGOTIATING and multi-source cancel), ContractDocument (sign/decline fork + supersede), PaymentRecord (parallel `capture_status` × `settlement_status` dimensions), BackupAssignment (offer cycle + promote), SongRequest (accept/conflict).
- **2 concurrency rules**: OCC on `Booking.version` for `promote-backup` and `issue-contract`.
- **6 calculations**: booking_quote_total (provisional), overtime_charge (final, ceil-block threshold), travel_fee (home-zone waiver + surge), cancellation_fee (tiered lead-time + CONFIRMED surcharge, ordered evaluation), deposit_required, backup_promotion_selector (rank → reliability → created_at, no `id`).
- **21 validations** (priority-ordered), **45 endpoints** (incl. reverse-reachability lists, `/_clock/set`), **21 errors**, **4 RBAC roles** (StudioAdmin + BookingAgent opaque; Performer + Client entity-backed).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8): all **9 Difficulty Rules × 2 instances = 18 instances**, each with executable `setup_api_calls`/`trigger` chains and code-computed literal asserts (e.g. quote 324000, overtime 6000, cancellation 64800, store-credit conservation 64800+16200=81000).

**SCAFFOLD_CORNER_DESIGN.yaml** (§1.9): **45 instances across all 9 taxonomy sections** (44 active + 1 `excluded_because:` stub pointing to a valid §1.8 instance) — creation/not-found/defaults/computed-fields, valid/invalid/terminal transitions, calc boundaries, validation triggers, 7 FK reverse-reachability reads, RBAC denials, OCC stale/correct, cascades, and immediate-consistency.

Note: `api_prefix` is `/` since entities are flat peers under distinct top-level collections (required for the lint's FK collection-segment derivation).

## Step 3: Copy Shared Files — 2026-06-14T13:28:44.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-14T13:35:25.000Z

PRD generation complete. The document is written to `workspace/PRD.md`.

**Line count:** 256 lines.

**Sections:** 5 top-level (Introduction; Global Specifications with 8 subsections 2.1–2.8; Business Logic with 11 subsections 3.1–3.11; Endpoint Definitions; Error Code Catalogue).

**What it documents:**
- **11 entities** — Performer, TravelZone, PackageOffering, EquipmentItem, Booking, Client, PaymentRecord, SongRequest, ContractDocument, BackupAssignment, BlackoutWindow (the last carrying only `id`/`created_at`, no `updated_at`/`version`, stated explicitly).
- **6 state machines** — Booking (9-state cyclic lifecycle with a CONTRACT_SENT↔NEGOTIATING loop and four cancel entry points), ContractDocument (branching SIGNED/DECLINED/SUPERSEDED fork), PaymentRecord (two parallel dimensions: capture_status and settlement_status), BackupAssignment (cyclic offer loop + promote path), SongRequest (flat ACCEPTED→CONFLICTED).
- **6 calculations** — travel_fee (home-zone waiver + basis-point surge, half-up), booking_quote_total (pinned eval order: equipment summed before travel), overtime_charge (ceil per started 15-min block, with boundary cases), cancellation_fee (4 lead-day tiers + CONFIRMED +10pp surcharge capped at 100%, floor-day via 86400), deposit_required, backup_promotion_selector (rank ASC / reliability DESC / created_at ASC, never id).
- **21 validations** with explicit priority ordering prose in §2.8.
- **45 endpoints** (4-column table: Method, Path, Description, Authorized Roles).
- **21 errors** (2-column table: Error ID, HTTP Status).
- **4 roles** — StudioAdmin (opaque), BookingAgent (opaque), Performer (entity-backed), Client (entity-backed), with each `identity` translated into ownership prose in §2.1.

**Deliberate information-scattering choices:** endpoint input params split across ≥2 subsections (OCC `expected_booking_version` in §2.7 & §3.5/§3.11; `actual_set_minutes` only in §3.7); quote formula split (components/eval order §3.4, zone fields §3.1); numeric thresholds embedded in narrative; OCC framed purely in stale-version terms; §3 contains zero HTTP methods/paths.

**Hard Contract reports:** Contract 1 (field coverage 0 missing) PASS; Contract 2 (rule coverage) PASS; Contract 3 (§3 path purity, 0 violations) PASS.

## Step 5: Generate Unit Tests — 2026-06-14T13:48:44.000Z

Generated complete test infrastructure for `task_0355_dj_live_entertainment_booking` from the four input files plus the unit-test-generator skill spec.

**Test files (5) — 78 tests total:**
- `test_01_quote_and_money.py` (16) — quote/deposit/travel/overtime/cancellation-fee math
- `test_02_lifecycle_and_state.py` (15) — booking/contract/payment state machines, negotiation cycle, parallel payment dimensions, cross-entity gating
- `test_03_cascades_and_backups.py` (9) — cancel-refund cascades, store-credit conservation, backup promotion swaps
- `test_04_validations_and_errors.py` (17) — temporal/fiscal/backup constraints, validation-ordering conflicts
- `test_05_crud_rbac_and_occ.py` (21) — CRUD, FK/enum/required-field checks, reverse-reachability listings, RBAC, OCC

**Queue split:** 34 tests from queue A (Difficulty), 44 from queue B (Corner).

**Coverage:** Queue A: all 17 covered difficulty instances × exactly 2 tests each. Queue B: all 44 non-stub corner instances × 1 test each. The single `excluded_because` stub (`occ_stale_promote_backup_rejected`) correctly not translated.

**Skipped under PRD-first filter (1 instance):** `Difficulty/resource_temporal_overlap/double_booking_closed_buffer_on_performer_bookings` — asserts a closed 4-hour buffer around `event_start_utc`; PRD §3.3 never defines the buffer arithmetic or set-window semantics, so outcome is not uniquely derivable. Gap left as gap. (Queue A covers 17 of 18 difficulty instances.)

**test_helpers files emitted (9):** `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`.

**Verification passed:** all files byte-compile; every test docstring ends with exactly one `Design:` line resolving to a real instance; all 105 PRD citations survive literal grep; no scaffold leakage; no skip/skipif/xfail markers.

## Step 6: Generate Implementation — 2026-06-14T13:48:44.000Z

Generated a complete Python + Flask implementation for the DJ & Live Entertainment Booking API in `workspace/implementation/`.

**Files emitted (14):** `start.sh`, `requirements.txt` (flask==3.0.3), `app.py`, `db.py`, `response.py`, `clock.py`, `timeutil.py`, `errors.py`, `middleware.py`, `validate.py`, `calculations.py`, `services.py`, plus `routes/` (catalogue, bookings, contracts, payments, songs, backups).

**Endpoints: 45** (full §1.5 / PRD §4 coverage).

**State machines:** Booking (INQUIRY→HOLD→CONTRACT_SENT⇄NEGOTIATING→CONFIRMED→PERFORMING→PERFORMED→SETTLED + cancel from {HOLD, CONTRACT_SENT, NEGOTIATING, CONFIRMED}; CONFIRMED reached as system cascade from deposit capture); ContractDocument (ISSUED→{SIGNED,DECLINED,SUPERSEDED}); PaymentRecord (parallel capture AUTHORIZED→{CAPTURED,VOID} × settlement UNSETTLED→{SETTLED,REFUNDED}); BackupAssignment (OFFERED→{ACCEPTED→PROMOTED,DECLINED,EXPIRED}); SongRequest (ACCEPTED/CONFLICTED at-create, case-insensitive title+artist vs DO_NOT_PLAY).

**Calculations (Decimal, ROUND_HALF_UP, cents):** travel_fee (home-zone waiver + bps surge), quote_total (pinned order, equipment before travel), deposit_required, overtime (ceil per 15-min block), cancellation_fee (lead-day tiers + CONFIRMED +10pp cap 100%), backup selector (rank ASC / reliability DESC / created_at ASC).

**Notable:** validation precedence (FK existence priority 5 before generic well-formedness priority 6); OCC `expected_booking_version` on issue-contract & promote-backup → `ERR_STALE_BOOKING_VERSION` (412); BlackoutWindow sole immutable entity; all requests serialized behind a single RLock; in-memory dicts only (no SQLite/JSON/tmp); nothing seeded.

**Boot:** `start.sh` cd's to its dir, guards pip install on `import flask`, then `exec python3 app.py` binding `0.0.0.0:$PORT` (default 10000, threaded). Fresh boot yields empty state; logical clock resets on restart. Three end-to-end smoke suites pass.

## Step 7: Test/Fix Iteration Loop — 2026-06-14T14:00:09.000Z

All clean. The task is complete — every test passes deterministically across two consecutive full 8-round parallel sweeps (16 rounds total, 78/78 each).

**Iterations run:** 1 fix iteration (baseline sweep → diagnose 5 union failures → fix → 2 confirmation sweeps, all clean).

**Baseline:** 73–74/78 per round. Union of failures across the 8 baseline rounds: 5 tests (4 deterministic, 1 flaky restart).

**Tests deleted:** None. All 5 failures traced to genuine PRD-derivable rules that were either implementation bugs or fixable test bugs.

**Fixes applied to `implementation/`:**
- `workspace/implementation/db.py` — `new_id()`: changed `uuid.uuid4().hex` → `str(uuid.uuid4())`. PRD §2.4 says verbatim "a server-minted **UUID** with no type prefix"; the dash-stripped `.hex` form is not a canonical UUID and failed the suite's `is_valid_uuid` check (requires the 36-char dashed v4 form). Fixed `test_create_performer_returns_201_with_system_fields`, `test_blackout_window_carries_only_id_and_created_at`.
- `workspace/implementation/start.sh` — replaced the per-boot `python3 -c "import flask"` probe with a one-time filesystem sentinel. The probe spawned an extra interpreter on every per-test reboot (78 tests × 8 concurrent rounds); under 8× concurrent CPU saturation this lengthened boot latency and intermittently tripped the runner's 15s "could not be restarted" window. Eliminated the flaky `test_stale_issue_contract_rejected` setup failure. The sentinel is a build marker, not entity state, wiped between runs without affecting correctness.

**Fixes applied to `test_suite/` (assertion mistranslations — STEP 2 test bugs):**
- `test_suite/test_02_lifecycle_and_state.py` — `test_negotiation_cycle_*`: assertion expected revision-1 contract to end `SUPERSEDED`. PRD §3.5 says request-revision "cascades the current contract's `status` to `DECLINED`" first, and re-issue only "supersedes any **still-`ISSUED`** contract" — by then revision 1 is already DECLINED, so nothing supersedes it. Corrected assertion to `DECLINED` (renamed test/docstring to match). No faithful PRD-only impl could produce SUPERSEDED here.
- `test_suite/test_04_validations_and_errors.py` — `test_promote_with_empty_backup_pool_rejected`: test passed a nonexistent `backup_assignment_id` expecting `ERR_NO_ELIGIBLE_BACKUP`, but PRD §2.8 orders body FK existence (`ERR_REFERENCED_ENTITY_NOT_FOUND`) before the backup business rule — a bogus id can never reach the no-eligible-backup branch. Fixed setup to offer-then-decline a real backup, leaving a resolving assignment id with an empty ACCEPTED pool, faithfully reaching `ERR_NO_ELIGIBLE_BACKUP` while respecting §2.8 precedence. Exact-error assertion preserved.

**Fixes applied to `test_helpers/`:** None — existing helpers (`offer_backup`, `decline_backup`, `make_performer_headers`) reused as-is.

**Final state:** Two consecutive full 8-round parallel sweeps (16 rounds), every round 78/78, empty union of failures.

## Step 8: Finalize PRD — 2026-06-14T14:12:00.000Z

The patch is in place: a single in-line edit to §2.4, line count unchanged at 256.

**PRD.md vs PRD_FINALIZED.md:** 256 vs 256 lines (0% line-count delta; one line revised in place).

**Changes (one bullet):**
- §2.4 Common Resource Properties — revise — pinned the entity `id` UUID format to the canonical 36-character lowercase hyphenated form (excluding the dash-stripped 32-char hex form), and noted `id` is the only field affected (api_request_id keeps its `req_` prefix). — `implementation/db.py:55` (`return str(uuid.uuid4())`)

**Items that produced NO edit (already uniquely pinned, or non-behavioral):**
- Negotiation cycle — PRD §3.5 already states verbatim request-revision "cascades the current contract's status to DECLINED" and re-issue "supersedes any still-`ISSUED` contract"; revision 1 is already DECLINED by re-issue time. Already uniquely determined → no edit.
- Promote-empty-pool — PRD §2.8 already orders body-FK existence (`ERR_REFERENCED_ENTITY_NOT_FOUND`) before business rules. Already uniquely determined → no edit.
- start.sh sentinel — boot-robustness build-marker, no behavioral/PRD surface → no edit.

**Pre-edit search log (Edit 1, §2.4 UUID):** subject = format of system-minted entity `id`; enumerated `new_id`/`uuid`/`api_request_id`/`req_` usages (`db.py:52-55` sole id generator via `str(uuid.uuid4())`; `db.py:63` `make_common` only caller used by every entity incl. BlackoutWindow; `response.py:28,33` independent `req_`-prefixed api_request_id); wording scoped to exclude `api_request_id` so the canonical-dashed claim doesn't falsely extend to the request id.

## Step 7 (orchestrator verification, continued) note: Re-ran independently after Step 7 exit. A single sequential round = 78/78 clean. First fresh 8-round sweep showed 1 transient `errors` (`test_booking_create_on_retired_package_rejected` — "API server could not be restarted" boot-timeout, 15.3s) caused by host CPU saturation overlapping a concurrent verification run; deterministic within that one loaded sweep but **not** a logic defect. A second fresh 8-round sweep was fully clean (8/8 rounds 78/78, 0 errors). Final `results.{1..8}.json` reflect the clean sweep.

## Step 9: Complete PRD — 2026-06-14T14:19:09.000Z

All 16 edits in place and minimal (in-paragraph/in-table inserts, no new sections or paragraphs). Line count unchanged at 256; char delta +2911.

**File metrics:** `PRD_FINALIZED.md` (base) 256 lines / 39,078 chars → `PRD_COMPLETED.md` 256 lines / 41,989 chars; char delta +2,911; line delta 0.

**Change counts:** 16 total — 9 ambiguity-pins, 7 mismatch-revisions.

**Per-change log:**
- §2.1 — insert — ambiguity — Client reading another client's Client/contract/payment/song-request (or a booking's contract/payment/song-request list) → `ERR_NOT_RESOURCE_OWNER`; booking reads not owner-scoped — `routes/catalogue.py:305`, `routes/contracts.py:19`, `routes/payments.py:53`, `routes/songs.py:82`
- §2.3 — insert — ambiguity — same-`created_at` rows tie-break by stable insertion order — `validate.py:127`
- §2.6 — revise — mismatch — added `home_zone_id` to body-FK reference list (`ERR_REFERENCED_ENTITY_NOT_FOUND`) — `routes/catalogue.py:155`
- §3.1 — insert — ambiguity — duplicate `zone_code` → `ERR_INVALID_REQUEST` (422) — `routes/catalogue.py:40-42`
- §3.1 — revise — mismatch — travel-zone `name` optional — `routes/catalogue.py:35`
- §3.1 — revise — mismatch — equipment `label` optional — `routes/catalogue.py:117`
- §3.3 — insert — ambiguity — client duplicate `email` → `ERR_INVALID_REQUEST` (422) — `routes/catalogue.py:285-287`
- §3.3 — insert — ambiguity — hold with performer `BOOKED`/`INACTIVE` → `ERR_INVALID_STATE` — `routes/bookings.py:153-154`
- §3.3 — insert — ambiguity — double-booking comparison target + half-open set-window overlap — `routes/bookings.py:175-189`
- §3.5 — insert — ambiguity — issue-from-HOLD with captured DEPOSIT → `ERR_INVALID_STATE` — `routes/bookings.py:227-230`
- §3.6 — insert — ambiguity — capture of non-`AUTHORIZED` payment / against `CANCELLED`/`SETTLED` booking → `ERR_INVALID_STATE` — `routes/payments.py:83-86`
- §3.6 — insert — ambiguity — `balance_due_cents` basis (quote_total pre-PERFORMED, final_total at PERFORMED/SETTLED) — `services.py:41-53`
- §3.7 — insert — ambiguity — start-set before clock reaches `event_start_utc` → `ERR_INVALID_STATE` — `routes/bookings.py:305-306`
- §3.9 — revise — mismatch — refund only still-`UNSETTLED` captured payments, refundable portion floored at 0 — `routes/bookings.py:390-398`
- §3.10 — revise — mismatch — `priority` recorded (default 100, ≥1) on DO_NOT_PLAY though ignored — `routes/songs.py:29`
- §3.11 — insert — ambiguity — `backup_assignment_id` resolving to none / different booking → `ERR_REFERENCED_ENTITY_NOT_FOUND` (404); accept of non-`OFFERED` / `BOOKED`/`INACTIVE` candidate → `ERR_INVALID_STATE` — `routes/bookings.py:442-445`, `routes/backups.py:88-92`
- §4 (table) — revise — mismatch — actual query-param filter sets for `GET /performers`, `GET /bookings`, `GET /bookings/{id}/song-requests`, `GET /bookings/{id}/backup-assignments`, `GET /backup-assignments` — `routes/*.py`

All other impl behaviors (envelope shape, UUID format, money rounding, cancellation tiers, overtime blocks, state transitions, RBAC matrix, OCC, blackout overlap, conflict detection, settlement) were already uniquely pinned by the base PRD and left unchanged.

---

## Pipeline complete — 2026-06-14T14:19:09.000Z

All 9 steps executed. Final state: 78 tests, all passing across a clean 8-round parallel sweep (`results.{1..8}.json`). Artifacts present: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml, workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}, test_helpers/, test_suite/.
