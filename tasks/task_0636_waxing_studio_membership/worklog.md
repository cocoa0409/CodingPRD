# Worklog — task_0636_waxing_studio_membership

Scenario: 636. Waxing Studio Membership (European Wax Center style): service menu & reservation, wax-pass/membership & prepaid credits, first-service-free intro, technician & room scheduling, product retail attach, package rollover & freeze, no-show/late & deposit, multi-location

Difficulty band: Expert (passed only to Step 2 scaffold generator).

## Step 1: Create task directory — 2026-06-23T00:00:00.000Z

Task directory `tasks/task_0636_waxing_studio_membership` pre-assigned and pre-created. Skipped max-index scan per orchestrator directive. Ensured `workspace/` subdirectory exists (already present).

## Step 2: Generate Scaffold (Expert band) — 2026-06-23T03:00:00.000Z

Generated all three scaffold artifacts for **task_0636_waxing_studio_membership** at the **Expert** difficulty band, written purely from the scenario + skill spec (no sibling tasks consulted). All files pass `scaffold_lint.py` with `VERDICT: clean lint`.

**Files written** (all in `tasks/task_0636_waxing_studio_membership/`):
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**Entity list (11):** Location, ServiceType, Product, Room, Technician, Member, Membership, CreditLedgerEntry, Reservation, RetailSale, NoShowStrike.

**Counts:**
- State machines: **5** — Membership (branching+cyclic: ACTIVE↔FROZEN, PAST_DUE branch), Reservation booking axis + Reservation settlement axis (parallel dimensions), RetailSale, NoShowStrike.
- Calculations: **7** (reservation_charge, membership_cancel_valuation, bookable_credit_check, retail_net, cycle_rollover_settlement, membership_credit_balance, active_strike_count) — incl. 2 dual-variant + 3 combinatorial modes (a/b/c).
- Validations: **18** (priority-ordered).
- Endpoints: **45** (config CRUD, booking/membership/retail actions, reverse-reachability GETs for all 16 FKs, 2 `/_clock` test-driving endpoints with default `2026-01-01T00:00:00Z`).
- Error codes: **18**.
- Roles: **4** (StudioAdmin, FrontDesk — opaque; Technician, Member — entity-backed).
- Concurrency rules: **2** (OCC on Room.version and Membership.version, both on `POST /studio/reservations`).

**§1.8 difficulty instances: 18** (9 rule_ids × 2 each). **§1.9 corner instances: 52 entries** = 41 active test recipes + 11 `excluded_because` stubs.

## Step 3: Copy Shared Files — 2026-06-23T03:00:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_0636_waxing_studio_membership/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-23T03:04:00.000Z

Generated PRD at `workspace/PRD.md` (261 lines, 44967 bytes) from SCAFFOLD.yaml only. Both withheld design files NOT read (confirmed by subagent).

Major sections: §1 Introduction; §2 Global Specs (RBAC, response structure, pagination, identity/versioning, cascades, OCC, operating hours, precision, nested-ref resolution, logical clock); §3 Business Logic (studio config, member/membership issuance, membership lifecycle + rollover, reservation booking with 18-rule priority order, first-visit & no-show deterrent, dual booking/settlement axes, retail attach, time sweeps); §4 Endpoint Definitions (46 endpoints, 4-col table); §5 Error Catalogue (18 error IDs).

Hard contracts all PASS: 70/70 field names verbatim; all state transitions + 2 OCC rules + 6 calculations + 18-rule priority ordering + cascades covered; §3 path-purity 0 violations; §2.2 byte-for-byte canonical.

## Step 5: Generate Unit Tests — 2026-06-23T03:07:00.000Z

Test files emitted: 12 in `test_suite/` (plus `conftest.py`). Total test functions: **75** (each with exactly one `Design:` tag; no untagged/dual-tagged/broken-pointer).
- Queue-A (Difficulty): 34 tests covering 17 of 18 instances (2 each).
- Queue-B (Corner): 41 tests covering all 41 non-stub instances (≥1 each); 11 `excluded_because` stubs correctly not translated.

Instances SKIPPED (1):
- Unique-derivability failure: `Difficulty/cross_entity_state_dependency/retail_confirm_requires_reservation_completed` — PRD §3.7 states the precondition (confirm only after attached visit COMPLETED) but does not name the error; faithful reader could return ERR_RESOURCE_MISMATCH instead of ERR_INVALID_STATE. Outcome not pinned → skipped.

test_helpers/ files (10): `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py` (+ barrel). Verification: py_compile clean; 75 tests collect; all 117 PRD citation fragments survive verbatim grep; no skip/xfail.

## Step 6: Generate Implementation — 2026-06-23T03:07:00.000Z

Built Python + Flask implementation at `workspace/implementation/` (18 files). 45 routes (exact match to PRD §4 table). Storage in-memory only (dicts in `db.py`) — no SQLite/file/JSON/tmp; no seeding (all 11 stores count 0 at boot, clock at default `2026-01-01T00:00:00Z`). start.sh reads `$PORT` (default 10000), binds `0.0.0.0`, runs foreground via `exec python3 app.py`; flask-install guarded against per-test-reboot contention.

Files: start.sh, requirements.txt, app.py, db.py, clock.py, errors.py, response.py, auth.py, helpers.py, mutate.py, util.py, serializers.py, credits.py, strikes.py, membership_service.py, reservation_service.py, retail_service.py, sweeps.py. Two in-process flask-test-client suites (35 checks) all passed.

## Step 7: Run Tests and Iterate — 2026-06-23T03:25:00.000Z

All tests pass cleanly across the full 8-round parallel sweep.

**Iterations run:** 2 (1 baseline sweep + 1 verification sweep). Both diagnostic-protocol fixes landed in a single fix batch; the verification sweep was clean across all 8 parallel rounds (75/75 each).

**Baseline:** 3 stable failures (identical across all 8 rounds — no flakiness). No tests required deletion: all three were PRD-covered and uniquely derivable.

**Tests deleted:** None.

**Fixes applied to test_suite/ (STEP 2 — test bug, fixture issued a request inconsistent with PRD):**
- `test_suite/test_01_reservation_charge_and_axes.py`, `test_deposit_charge_provisional_quote_differs_from_final` and `test_walk_in_final_charge_is_list_price`: both booked a reservation at `start_utc=2026-06-20T10:00:00Z` but called `check_in()` while the clock was still at the setup value `2026-06-15T12:00:00Z`. PRD 3.6 requires check-in only "once the clock has reached at least 30 minutes before `start_utc`," so the PRD-faithful implementation correctly returned `ERR_CHECKIN_TOO_EARLY`. Added `set_clock("2026-06-20T09:45:00Z")` before each `check_in` (matching the pattern the credit tests already use), making the tests faithful to PRD without weakening any assertion.

**Fixes applied to implementation/ (STEP 3 — implementation violated a verbatim PRD invariant):**
- `workspace/implementation/reservation_service.py`, `create_reservation` (booking side-effects): for an `UNLIMITED`-tier CREDIT booking the code unconditionally wrote a `DEBIT` of `-credit_cost`, driving `credit_balance` to `-1`. This violated PRD 3.2 ("The balance must never drop below zero — a debit that would drive it negative is refused before it is written") and PRD 3.3 ("An `UNLIMITED` tier never accumulates a numeric balance"). Gated the DEBIT and `credits_held` assignment on `tier != "UNLIMITED"`: UNLIMITED bookings still succeed (eligibility treats balance as unbounded, PRD 3.4), still set `settlement_status="CREDIT_HELD"`, and still advance the membership `version` per PRD 3.4 — but write no DEBIT and hold `credits_held=0`, so the balance stays 0 and the existing `credits_held > 0`-gated refund paths remain neutral for UNLIMITED.

Final state: 8/8 parallel rounds pass, 75/75 tests each.

## Step 8: Finalize PRD — 2026-06-23T03:52:25.385Z

The patch is complete. One line edited (line 148), minimal change.

## Summary

**Line counts:** PRD.md 261 lines → PRD_FINALIZED.md 261 lines (one line revised in place; 0% line-count delta — the change is within a single paragraph).

**Changes (one bullet per change):**
- **PRD 3.4** — *revise* — pinned the `UNLIMITED`-tier `CREDIT` booking behavior: a non-`UNLIMITED` tier writes the `DEBIT` of `-credit_cost` and sets `credits_held=credit_cost`, but an `UNLIMITED` tier writes no `DEBIT` and leaves `credits_held=0` (effective balance treated as unbounded), while both cases still move settlement to `CREDIT_HELD` and advance the membership `version` by 1 — `reservation_service.py:150-204` (gate at lines 157-158, 201-204; unconditional `touch(membership)` at 204).

**Step 7 items NOT requiring a PRD edit:**
- **STEP 2 (test fixture bugs)** — the two check-in-too-early tests set the clock to a value before the 30-minutes-before-`start_utc` window. PRD 3.6 already uniquely determines the check-in window ("only once the clock has reached at least 30 minutes before `start_utc` ... `ERR_CHECKIN_TOO_EARLY`"), and `reservation_service.py:248-255` matches it exactly. Pure fixture bug; no PRD silence or mismatch. No edit.

**Per-edit pre-edit search log:**

*Edit 1 (PRD 3.4 UNLIMITED credit booking):*
- **(a) Subject:** UNLIMITED-tier CREDIT booking — DEBIT write, `credits_held` value, `CREDIT_HELD` settlement, membership `version` advance, and downstream credit-refund cascades.
- **(b) Paths enumerated (grep `credits_held|UNLIMITED|CREDIT_HELD|DEBIT|credit_cost`, read in full):**
  1. `reservation_service.py:146-208` — booking side effects: `credits_held=0` default, DEBIT gated on `tier!="UNLIMITED"` (157-158, 201-203), `touch(membership)` unconditional for CREDIT (204), `settlement_status="CREDIT_HELD"` unconditional (151).
  2. `reservation_service.py:138-141` — credit-sufficiency: UNLIMITED skips balance check (unbounded).
  3. `reservation_service.py:164-172` — provisional `charged=0` for CREDIT (incl. UNLIMITED) — already covered by PRD 3.6 ("`CREDIT` hold quoted 0").
  4. `reservation_service.py:324-336` (`_settle_refund`) and `377-387` (`release_credits_for_membership_cancel`) — both gated on `credits_held > 0`; UNLIMITED `credits_held=0` ⇒ neutral.
  5. `membership_service.py:21,65` — grant=0 for UNLIMITED (activation/renewal); `93-119` cancel par-value forfeit — UNLIMITED balance stays 0 ⇒ no forfeit. Already implied by PRD 3.3.
- **(c) Wording adjustment:** Scoped the DEBIT/`credits_held` write to "non-`UNLIMITED` tier" and split the `version` advance into an "in every case" clause so the universal version-bump (which fires for UNLIMITED too) is not narrowed; added "leaves `credits_held` at 0" so the refund-cascade paths (gated on `credits_held > 0`) remain correctly described as neutral for UNLIMITED. No path is mis-described by the new sentence.

## Step 9: Complete PRD — 2026-06-23T04:00:16.981Z

All edits are in place and render cleanly. The work is complete.

## Summary

Produced `/home/ubuntu/github/CodingPRD/tasks/task_0636_waxing_studio_membership/workspace/PRD_COMPLETED.md` as a minimal in-paragraph patch over `PRD_FINALIZED.md`, pinning every spot where the PRD was silent or mismatched against `implementation/`.

**Counts**
- Source `PRD_FINALIZED.md`: 261 lines, 45,399 chars
- `PRD_COMPLETED.md`: 261 lines, 49,310 chars (char delta +3,911; no lines added — all edits in-paragraph, no new sections)
- Ambiguity-pins: 6; Mismatch-revisions: 5 (11 edits total)

**Changes (one per edit)**
- §2.1 — insert — ambiguity — `Member` read-scoping: single-`GET`/list is ownership-restricted only on memberships, retail sales, and no-show strikes; locations/service-types/products/rooms/technicians/members/reservations reads are unscoped — `app.py:419-442,628-633,683-706` vs unscoped `app.py:528-550,367-372`
- §2.2 — insert — ambiguity — `api_request_timestamp` reflects the logical clock, not wall time — `response.py:14`
- §2.3 — insert — ambiguity — list tie-break is ascending write-sequence (never `id`); `has_more` formula pinned — `app.py:74`, `response.py:35`
- §2.6 — revise — mismatch — `expected_membership_version` is consulted only when supplied; its omission on a credit booking is not a well-formedness error (PRD said "required") — `reservation_service.py:33-35,73-80`
- §3.3 (renewal) — revise — mismatch — renewal is also authorized for `StudioAdmin`; `payment_outcome` enum + not-met-precondition `ERR_INVALID_STATE` cases pinned (PRD prose said FrontDesk only) — `app.py:482`, `membership_service.py:72-81`
- §3.3 (settlement) — insert — ambiguity — `cycle_index` is incremented before the renewal's `ROLLOVER_FORFEIT`/`GRANT` entries are written, so they carry the new index — `membership_service.py:85-87`
- §3.3 (cancel) — insert — ambiguity — par-value forfeit is recorded via a `ROLLOVER_FORFEIT` ledger entry of `-remaining`; wallet credited only when remaining > 0 — `membership_service.py:110-116`
- §3.4 (gauntlet) — revise — mismatch — actual guard order: auth → role-authz → well-formedness → existence → ownership → OCC (PRD ordered ownership and existence before well-formedness) — `reservation_service.py:22-68`
- §3.6 (late cancel) — revise — mismatch — voided `PENDING` retail sale has no stock change (PRD said "restocked") — `reservation_service.py:368-374`
- §3.6 (no-show) — insert + revise — ambiguity/mismatch — manual mark-no-show precondition failure returns `ERR_INVALID_STATE` (no dedicated too-early error); void has no restock — `reservation_service.py:304-309,368-374`
- §3.7 (retail attach) — insert — mismatch — existence resolution order is Member → Reservation → Product (not the global §2.9 Product-before-Reservation order) — `app.py:611-619`

Tests were used only as auxiliary cross-reference; none of the pinned behaviors were probed by assertions, confirming these were genuine PRD silences/mismatches rather than already-tested contracts.
