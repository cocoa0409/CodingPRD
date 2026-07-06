# Worklog — task_0532_utility_locate

## Step 1: Create task directory — 2026-07-01T00:00:00.000Z

Created `tasks/task_0532_utility_locate/workspace/` (task dir pre-allocated). Verified `INSTRUCTION.md` exists at project root.

## Step 2: Generate scaffold — 2026-07-01T00:01:00.000Z

Generated a complete **Expert-difficulty** scaffold for **task_0532_utility_locate** (811 Call-Before-You-Dig & Utility Locate) in three files. `scaffold_lint.py` reports **VERDICT: clean lint** (357 setup/trigger calls scanned; all 16 FKs have reverse-reachability GETs).

**Complexity profile:** primary archetype multi-party negotiation (unanimous member all-clear quorum) + secondary temporal windowing; flat topology; compound (posture-driven) state shape; peer_roles; layers = cascading side effects, derived-field reconciliation, rate/threshold triggers, optimistic concurrency, scheduled/deferred (logical clock, default `2026-05-01T00:00:00Z`).

**SCAFFOLD.yaml (§1.0–§1.7):**
- **10 entities:** Excavator, MemberUtility, LocateTech, LocateTicket, UtilityNotification, PositiveResponse (append-only), LocateAssignment, MarkOut, MeetRequest, DamageReport.
- **6 state machines:** LocateTicket (compound, posture-driven, clock auto-expiry), UtilityNotification (3-way branch), LocateAssignment (dispatch + SLA-breach auto-transition), MarkOut (cyclic re-mark/refresh loop), MeetRequest, DamageReport (branch settle/dispute).
- **1 concurrency rule:** OCC `markout-refresh-stale-ticket` on `LocateTicket.version` (412).
- **5 calculations:** `sla_due_at` (dual-variant emergency-flat vs normal-business-day-skip), `liability_apportionment` (dual-variant marked vs no-marks, round_half_up), `assignment_sla` (3-input non-linear), `dig_window` (pinned evaluation order), `response_posture` (compound aggregate).
- **11 validations** (priority-ordered incl. a 5.5 tech-availability check), **50 endpoints** (incl. `/_clock/set_current_utc`), **44 error codes**, **5 RBAC roles** (Excavator/FacilityOwner/LocateTech entity-backed; CallCenter/Admin opaque).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** 9 rule_ids × 2 instances = **18 instances**, all with executable `setup_api_calls` chains and formula-derived literals.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **28 active instances + 4 `excluded_because` stubs** across 8 taxonomy sections; all stub references resolve to named §1.8 instances; all 49+ instance names unique across both design files.

## Step 3: Copy shared files — 2026-07-01T00:02:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-01T00:03:00.000Z

Generated `workspace/PRD.md` — prose PRD for the Utility Locate API (~330 lines). §1 Introduction; §2 Global Specifications (11 subsections, RBAC 5 roles, pagination, common props, PositiveResponse immutability, cascades, nested-retrieval L-to-R validation, shared-grid routing predicate, logical clock + deferred actions, precision, cents apportionment/round-half-up, OCC); §3 Business Logic (9 scattered subsections); §4 endpoint table (all 50); §5 error catalogue (all 44). Hard Contracts 1/2/3 all PASS. Confirmed the two design files were NOT read.

## Step 5: Generate unit tests — 2026-07-01T00:04:00.000Z

64 tests total: 36 from queue A (18 instances × 2) + 28 from queue B (28 non-stub × 1). Coverage is exact.

Generated complete test infrastructure for **task_0532_utility_locate** (811 Call-Before-You-Dig / Utility Locate, Expert band) under a strict design-index-only contract.

### Stage 1 — `test_helpers/` (9 files)
- **types.py** — role enum, 10 status enums, 11 entity TypedDicts. `PositiveResponse` correctly modeled as append-only (id + created_at only, no `updated_at`/`version`) per PRD §2.4.
- **api_client.py** — `ApiClient(GenericApiClient)` with one method per PRD endpoint (all 50+ routes incl. `/_clock/set_current_utc`).
- **api_errors.py** — full 43-error `ApiErrorId` enum + HTTP status map, registered via `set_error_http_status_map`.
- **assertions.py, factories.py, constants.py** — per-entity assertions (incl. `assert_liability_sums_to_cost`), input-only payload factories, PRD calculation constants.
- **test_users.py** — opaque shared headers (CallCenter/Admin) + per-instance `make_*_headers` builders for the three entity-backed roles (Excavator/FacilityOwner/LocateTech), with identity threading.
- **fixtures.py** — composite setup helpers tiered from party registration → submitted/cleared ticket → dispatch/en-route/mark-out → MARKED ticket → refresh cycle → damage reports → meet requests.

### Stage 2 — `test_suite/` (conftest + 5 files, 64 tests)
Every test translates exactly one non-stub design instance and ends with a verbatim `Design:` tag.
- Queue A (Difficulty): all 18 instances × 2 tests = 36 tests.
- Queue B (Corner): all 28 non-stub instances × 1 test = 28 tests.
- The 3 `excluded_because:` stubs were NOT translated; all cross-references verified.

### Verification
- All 14 files byte-compile. 18/18 difficulty at 2 tests each; 28/28 corner at 1 each. Every test carries exactly one Design tag. 18 distinctive citation substrings survive literal grep of PRD.md.
- No instances skipped — all 46 non-stub instances passed the PRD-first two-condition filter.

## Step 6: Generate implementation — 2026-07-01T00:05:00.000Z

Complete Python + Flask implementation of the 811 Utility Locate API (task_0532, Expert band) in `workspace/implementation/`. All files compile, server boots cleanly with an empty store.

### Files
- `start.sh` — guarded dependency install + `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `app.py` — all 50+ endpoints, error handlers, request envelope
- `services.py` — calculations, posture reconciliation, clock auto-transitions
- `models.py`, `db.py`, `clock.py`, `errors.py`, `auth.py`, `util.py`, `requirements.txt`

### Key behaviors implemented (validated end-to-end)
- Response envelope, error body, ISO-8601 UTC (3 fractional digits), pagination meta
- Auth: X-User-ID/X-User-Role headers, 5 roles, entity-backed ownership; precedence header→perm(403)→existence(404)→state(409)→ownership(403)
- Routing predicate: open-interior overlap both axes; only ACTIVE members
- sla_due_at: EMERGENCY +2h flat; NORMAL 2 business days skipping weekends
- assignment_sla: pinned order base→high-priority ×0.5 ceil→+60 load slack
- liability_apportionment: no-markout 100% excavator; marked 25/75 or 75/25 round-half-up, member share exact remainder
- Compound ticket posture derived from notifications with fixed precedence
- Mark-out refresh + OCC: expected_ticket_version → ERR_STALE_TICKET_VERSION (412); prior mark-out SUPERSEDED; dig window slides
- Clock-driven auto-transitions on /_clock/set_current_utc
- Meet overlap: half-open interval, touching endpoints allowed
- No seeding — store empty on every boot

## Step 7: Test and fix loop — 2026-07-01T00:06:00.000Z

All 8 rounds pass 64/64 with zero failures across the union. Clean sweep.

**Iterations run:** 2 (initial sweep found 13 deterministic failures; second sweep after fixes was clean 8/8).

**Tests deleted:** None. All 13 failing tests traced to PRD prose and were fixable via test-helper or implementation corrections.

**Fixes applied to `implementation/`:**
- `util.py` — added `iso_sec()` (second-granularity ISO 8601, no fractional digits) alongside existing `iso_ms()`. PRD §2.9 pins computed instants to second granularity, while §2.4 pins audit timestamps to three fractional digits — two distinct serialization formats.
- `models.py` — `serialize()`: split `_DT_FIELDS` into `_MS_DT_FIELDS` (`created_at`, `updated_at` → `iso_ms`) and `_SEC_DT_FIELDS` (all computed instants: `sla_due_at`, `dig_window_opens_at`, `dig_window_expires_at`, `markout_completed_at`, `due_at`, `responded_at`, `dispatched_at`, `sla_deadline_at`, `completed_at`, `valid_until` → `iso_sec`). Fixed the 10 datetime-format failures.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` — `setup_cleared_ticket()`: white-line NORMAL tickets (`is_white_lined=True`) so they satisfy the PRD §3.2 meet-request submission prerequisite; EMERGENCY tickets remain exempt. Fixed `test_assignment_sla_normal_lowload_baseline` (was failing setup with `ERR_MEET_REQUEST_REQUIRED`).

**Fixes applied to `test_suite/` (fixture-precondition bugs, per STEP 2):**
- `test_04_validations_and_boundaries.py` — `test_answered_notification_state_beats_ownership` and `test_answered_notification_second_owner_post_rejected`: made second member's `service_polygon` cover the dig site so both members are routed notifications, keeping ticket in `SUBMITTED` after one leg clears, isolating the `ERR_NOTIFICATION_ALREADY_ANSWERED` guard (PRD §3.4 orders ticket-state before notification-state).
- `test_03_cascades_and_posture.py` — `test_cancel_ticket_blocked_by_active_assignment`: rewrote to a two-member ticket where mem_a's leg is cleared+dispatched and mem_b's leg stays PENDING, keeping the ticket in `SUBMITTED`. PRD §3.2 `ERR_ASSIGNMENT_ACTIVE` guard only applies when cancelling from `SUBMITTED`. Added `get_notification_for_member` import.

The implementation's error precedence and cancel/dispatch guards were PRD-faithful throughout; no PRD-required checks were weakened.

## Step 8: Finalize PRD — 2026-07-01T00:07:00.000Z

Wrote `workspace/PRD_FINALIZED.md`. PRD.md = 298 lines; PRD_FINALIZED.md = 298 lines. One line revised in place (§2.9). %-delta ≈ 0%.

### Change
- §2.9 — revise — pinned the serialization format of computed-instant datetime fields to second granularity (no fractional digits, trailing `Z`), explicitly distinguished from the three-fractional-digit `created_at`/`updated_at` audit timestamps of §2.4; enumerated the exact computed-instant fields. — models.py:32-53 (`_SEC_DT_FIELDS` + `serialize()` using `iso_sec`) / util.py:32-43 (`iso_sec`).

### Why this is the only edit
Only the util.py + models.py datetime split traces to a PRD silence: §2.9 originally said computed instants are "evaluated at second granularity" but never pinned their serialization format. The other three fix categories are fixture/test-precondition bugs whose behaviors are already uniquely pinned in current PRD prose (§3.2 meet-request prerequisite + exemptions; §3.4 ticket-state before notification-state ordering; §3.2 ERR_ASSIGNMENT_ACTIVE scoped to cancelling from SUBMITTED).

## Step 9: Complete PRD — 2026-07-01T00:08:00.000Z

Wrote `workspace/PRD_COMPLETED.md`. PRD_FINALIZED.md (source) → PRD_COMPLETED.md: 298 → 299 lines (+1); 43,166 → 44,607 chars (+1,441). Counts: 8 ambiguity-pins, 1 mismatch-revision.

### Changes
- §2.2 (Error Response Format) — insert — ambiguity — non-object body / missing required field / null required field → ERR_INVALID_REQUEST (400), before reference/business checks — app.py:79,86.
- §2.6 (Reference Validation) — insert — ambiguity — no PositiveResponse not-found error; GET /positive-responses/{id} on unknown id → ERR_INVALID_REQUEST (400) — app.py:621.
- §2.8 (Logical Clock) — insert — ambiguity — unparseable to_iso8601 → ERR_INVALID_REQUEST; success returns data.current_utc as ISO-8601 UTC with three fractional digits — app.py:1089,1092 + util.py:29.
- §3.1 (Excavator) — revise — mismatch — removed "(unique among excavators)" claim; impl does not enforce contact_email uniqueness — app.py:210-224.
- §3.1 (MemberUtility) — insert — ambiguity — malformed service_polygon → ERR_INVALID_GEOMETRY — app.py:262-263.
- §3.1 (MemberUtility) — insert — ambiguity — facility_type outside six-member enum → ERR_INVALID_REQUEST — app.py:260-261.
- §3.1 (LocateTech) — insert — ambiguity — non-list certified_facility_types or out-of-enum value → ERR_INVALID_REQUEST — app.py:314-315.
- §3.2 (LocateTicket) — insert — ambiguity — ticket_type other than NORMAL/EMERGENCY → ERR_INVALID_REQUEST — app.py:364-365.
- §3.4 (PositiveResponse) — insert — ambiguity — outcome other than three enum values → ERR_INVALID_REQUEST — app.py:568-569.
- §3.8 (DamageReport) — insert — ambiguity — non-boolean dug_within_marks → ERR_INVALID_REQUEST — app.py:988-989.

All other impl behaviors were already uniquely pinned by existing PRD prose.

## Pipeline complete — task_0532_utility_locate

All 9 steps complete. 64/64 tests pass across all 8 parallel rounds under per-test-server isolation.
