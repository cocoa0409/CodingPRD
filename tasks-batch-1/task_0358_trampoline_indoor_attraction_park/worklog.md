# Worklog — task_0358_trampoline_indoor_attraction_park

## Step 1: Create Task Directory — 2026-06-15T00:00:00.000Z

Pre-assigned directory `tasks/task_0358_trampoline_indoor_attraction_park` used verbatim (no scan/auto-increment per orchestration override). Directory and `workspace/` already existed; verified present. Difficulty target: Expert.

## Step 2: Generate Scaffold — 2026-06-15T00:05:00.000Z

All three scaffold artifacts are generated, parse cleanly, and pass `scaffold_lint.py` with a clean verdict.

**Task:** `task_0358_trampoline_indoor_attraction_park` — Trampoline / Indoor Attraction Park. **Difficulty: Expert.**

**Files written** (all under `tasks/task_0358_trampoline_indoor_attraction_park/`):
- `SCAFFOLD.yaml` (§1.0–§1.7 + concurrency rules) — 1644 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, 18 instances) — 1085 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, 41 active + 8 `excluded_because` stubs) — 1456 lines

**Complexity profile:** primary archetype quota_allocation + secondary temporal_windowing; layers = OCC, cascading side effects, dual-variant calc, rate/threshold triggers, derived-field reconciliation, scheduled actions; topology flat; state-machine shape parallel (mixed: parallel + branching + cyclic); role_model peer_roles; consistency immediate.

**Entities (12):** Park, SessionSlot, Participant (self-referential guardian FK), Waiver, JumpPass, PassAddOn, Member, Membership, PartyRoom, PartyPackage, PartyBooking, IncidentReport.

**State machines (5):**
- JumpPass — **parallel** axes: admission (RESERVED→CHECKED_IN→COMPLETED, +CANCELLED/NO_SHOW) × payment (UNPAID→PAID→REFUNDED/PARTIALLY_REFUNDED).
- PartyBooking — **branching** fork at deposit (PENDING→DEPOSIT_HELD→CONFIRMED→CHECKED_IN→COMPLETED; divergent cancel side-effects per branch).
- Membership — **cyclic** ACTIVE↔PAST_DUE renewal loop + CANCELLED terminal.
- SessionSlot — derived posture OPEN/FULL/CLOSED gating seat consumption.
- IncidentReport — branching review (FILED→REVIEWED→SIGNED_OFF | FILED→VOIDED), SEVERE fires slot-close cascade.

**Calculations (7):** pass_pricing (inclusion vs discount variants), cancellation_refund (within-cutoff vs late variants), party_pricing (pinned discount-then-room-fee order), slot_seat_accounting (jump-seat vs party-guest-seats variants), membership_pricing (tiered), waiver_expiry, addon_pricing. All literals computed in code (e.g., 350/1850/3600 pricing, 4750/5313 deposits, 2350/350 refunds).

**Validations:** 18 priority-ordered rules. **Endpoints:** 55. **Errors:** 20. **Roles (4):** ParkManager (opaque), FrontDesk (opaque), Member (entity_backed:Member), Guardian (entity_backed:Participant). **Concurrency:** 2 OCC rules on SessionSlot.version (jump-pass create, party hold-deposit), both 412.

**Expert difficulty reflected:** §1.8 — all 9 Difficulty Rules × 2 instances (18 total), each with distinct differentiation (dual-variant calc, combinatorial modes, non-linear state shapes, depth-3 transitive cascades, priority conflicts across category pairs, boundary precision, cross-entity deps, temporal-overlap dual-semantics, compensating invariants). §1.9 — breadth walk across all 9 claim-extraction sections with `excluded_because` stubs.

**Note:** WALKIN jump-pass create path deliberately does NOT enforce waiver/window safety gate (those apply only to check-in endpoints, priorities 8–9); WALKIN passes are born CHECKED_IN.

## Step 3: Copy Shared Files — 2026-06-15T00:06:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-15T00:12:00.000Z

Generated `workspace/PRD.md` (299 lines) from the trampoline / indoor attraction park scaffold. DIFFICULTY/CORNER design files withheld.

### PRD section structure
- §1 Introduction (capacity contention, safety paperwork, money reconciliation, explicit logical clock).
- §2 Global Specifications (9 subsections): 2.1 RBAC; 2.2 fixed verbatim envelope; 2.3 Pagination; 2.4 Common Properties & Derived-Field Reconciliation; 2.5 Left-to-Right Reference Validation; 2.6 OCC on Slot Capacity; 2.7 Validation Ordering / Safety-Before-Fiscal; 2.8 Money/Seats/Rounding; 2.9 Logical Park Clock.
- §3 Business Logic (9 subsections by entity lifecycle): park config → session slots & seat accounting → participants/minors/guardians → waivers & safety gate → jump-pass two-axis lifecycle & pricing & add-ons → pay/check-in/complete/cancel & refund → members/tiers/renewal cycle → party rooms/packages/booking fork → incidents & severe-incident cascade.
- §4 endpoint table (56 endpoints); §5 error table (20 errors). No audit footer.

### Coverage
- Entities (12): Park, SessionSlot, Participant, Waiver, JumpPass, PassAddOn (id/created_at only, no updated_at/version), Member, Membership, PartyRoom, PartyPackage, PartyBooking, IncidentReport.
- Errors (20): all 20 IDs in §5 table + surfaced in narrative.
- State machines: all five (slot OPEN/FULL/CLOSED derived + close + severe cascade; JumpPass dual admission×payment axes; PartyBooking deposit fork divergent cancel branches; Membership cyclic ACTIVE↔PAST_DUE; IncidentReport FILED→REVIEWED→SIGNED_OFF / FILED→VOIDED).
- Calculations: pass_pricing (3-path, pinned order), cancellation_refund (cutoff-inclusive full vs late-partial min()), party_pricing (per-guest discount before room fee), slot_seat_accounting (status-filtered, closed-wins), membership_pricing (BRONZE/SILVER/GOLD constants), waiver_expiry (365d), addon_pricing (catalog 800/500/1500/2500).
- OCC: both rules with `expected_slot_version`, parent `SessionSlot.version`, `ERR_STALE_SLOT_VERSION` HTTP 412.

### Hard Contracts: all PASS (Field-Name Coverage 65 ids 0 missing; Rule Coverage; §3 Path Purity 0 violations).

### Notable: CHECKIN_LEAD_MINUTES (30 min) and WAIVER_VALIDITY_DAYS (365) embedded in prose; Member/Guardian entity-backed + ParkManager/FrontDesk opaque-operator identities in §2.1.

## Step 5: Generate Unit Tests — 2026-06-15T00:26:00.000Z

Generated complete test infrastructure for **task_0358_trampoline_indoor_attraction_park**.

### Stage 1 — `test_helpers/` (9 files)
`types.py` (entity TypedDicts + status/role enums; `PassAddOn` carries only `id`/`created_at` per `common_fields:false`), `api_client.py` (one method per PRD §4 endpoint, all 50+ routes), `api_errors.py` (20 error IDs + HTTP-status map), `assertions.py`, `factories.py` (input-fields only), `constants.py`, `test_users.py` (opaque ParkManager/FrontDesk constants + entity-backed `make_member_headers`/`make_guardian_headers`), `fixtures.py` (composite multi-step setup, correct Member-identity threading), `__init__.py` barrel. All compile.

### Stage 2 — `test_suite/` (6 test files + conftest)
**76 tests total**, every test tagged with exactly one `Design:` line + verbatim PRD citation (87 citations machine-verified against PRD.md).
- test_01_pricing_calculations.py (11), test_02_seat_accounting_and_capacity.py (16), test_03_state_machines_and_lifecycle.py (13), test_04_cascades_and_dependencies.py (12), test_05_validations_and_priority.py (10), test_06_crud_rbac_listing.py (14).

### Coverage
- Queue A (Difficulty): 17 of 18 instances covered, each ≥2 tests.
- Queue B (Corner): 40 of 41 non-stub instances covered, ≥1 test each. All 8 `excluded_because` stubs correctly NOT translated.

### Skipped instances (PRD-first filter failures — gaps left as gaps)
1. Difficulty `priority_pair_validation_conflict/room_conflict_state_beats_capacity_fiscal_on_hold_deposit` — PRD §3.8 lists capacity check before room-conflict; §2.7 never pins room-conflict-before-capacity. Fails unique derivability.
2. Corner `endpoints/addon_attach_to_terminal_pass_action_endpoint` — asserts ERR_INVALID_STATE attaching add-on to CANCELLED pass, but PRD §3.5 never states add-on attach is admission-state-gated. Fails unique derivability.

No skip/skipif/xfail emitted; no scaffold-table refs leaked.

## Step 6: Generate Implementation — 2026-06-15T00:26:00.000Z

Built complete Python + Flask implementation in `workspace/implementation/`.

### Files
- `start.sh` (foreground; guards pip install on `import flask` check; reads `$PORT` default 10000; `exec python3 app.py`)
- `app.py` (all 54 endpoints, error handlers, serializers, routes), `services.py` (calculations), `validation.py` (parsing/coercion/pagination/ISO-8601), `middleware.py` (auth + role checks), `response.py` (envelopes), `common.py` (system fields, round_half_up), `db.py` (in-memory store, one dict per entity), `errors.py`, `requirements.txt`.

### Endpoints: all 54 from PRD §4 (Park bootstrap+clock, SessionSlot CRUD/close/sweep/reverse lookups, Participant, Waiver, JumpPass create/pay/check-in/complete/cancel/add-ons, Member/Membership subscribe/renew/cancel, PartyRoom/PartyPackage, PartyBooking fork, IncidentReport file/review/sign-off/void, /health).

### Notable logic
- Boot/state: store starts empty every boot (no seeding); single global `Store()` wipes on each `start.sh` relaunch.
- Parallel state machines: JumpPass admission_status × payment_status independent; PartyBooking deposit fork; Membership cyclic ACTIVE↔PAST_DUE.
- Derived seat accounting recomputed from current passes+bookings on every consuming/releasing transition and on read; closed wins → CLOSED.
- Calculations all Decimal round-half-up: pass pricing (inclusion/discount/full, socks/add-ons never discounted), cancellation refund tiers (cutoff-inclusive boundary), party pricing (member discount on per-guest before room fee), deposit fraction, addon catalog.
- OCC: `expected_slot_version` on jump-pass create + party hold-deposit → ERR_STALE_SLOT_VERSION 412.
- Validation ordering §2.7 safety-before-fiscal: waiver gate beats capacity on check-in; room-conflict beats capacity on hold-deposit.
- SEVERE incident cascade force-closes pass's slot at file time.
- PassAddOn leaner (id + created_at only).

Self-verified ~58 assertions across smoke suites; fresh-boot wipe confirmed; all modules compile.

## Step 7: Run Tests and Iterate — 2026-06-15T00:42:00.000Z

**Outcome:** All 8 parallel rounds pass cleanly (76/76 each), confirmed across two consecutive full sweeps (16/16 rounds total).

**Iterations run:** 3 sweeps (1 diagnostic baseline + 2 verification after fixes).

**Diagnosis:** Every failure in the baseline sweep was a *boot/transport flake*, not an assertion failure — never a correctness, PRD-coverage, or test-faithfulness issue. Baseline showed 7 of 8 rounds at 76/76 with the 8th at 74/76, but *which* tests failed varied per round (all `"could not be restarted"` setup failures plus one `BadStatusLine` connection abort). Implementation logic and test suite were already PRD-faithful and correct.

Two distinct infrastructure root causes, both surfaced only under the 8x-concurrent per-test-restart load:
1. **Slow boot (5.3s → 0.24s).** Direct `bash start.sh` boot took 5.3s because Werkzeug calls `socket.getfqdn("0.0.0.0")` during `server_bind`, stalling ~5s on a macOS reverse-DNS timeout. Relying on the runner's injected patch left no margin under contention, occasionally pushing a boot past the 15s restart-poll window → `"could not be restarted"`.
2. **Stale keep-alive socket reuse → `BadStatusLine`/`Connection aborted` on `POST /park`.** The runner's `GenericApiClient` uses one persistent `requests.Session()` (keep-alive, no retries). Under per-test-server isolation the server is killed/respawned on the same port before each test; the first request of the next test could reuse a pooled socket left open from the now-dead server, aborting before the new handler ran.

**Tests deleted:** None. (No test failed STEP 1 coverage or STEP 1b unique-derivability; every failure was infrastructural.)

**Fixes applied to test_helpers/:** None. (Fixtures, factories, headers all PRD-consistent.)

**Fixes applied to implementation/** (`workspace/implementation/app.py`, transport/boot hardening only — zero change to any PRD-defined body, status code, error_id, or semantic):
- Module top: self-contained `socket.getfqdn` override returning `localhost` for unspecified addresses (`""`, `0.0.0.0`, `::`), so fast boot no longer depends on the runner's injected patch. Boot dropped 5.3s → 0.24s. Only the cosmetic Werkzeug startup-banner hostname is affected; server still binds `0.0.0.0`.
- `app.run(...)`: added `debug=False, use_reloader=False` to avoid a reloader double-forking a second interpreter under the concurrent restart sweep.
- New `@app.after_request` hook (`_no_keep_alive`): sets `Connection: close` on every response so the harness's persistent session tears its socket down after each request — no stale keep-alive socket survives a restart, eliminating the `BadStatusLine` race. Responses remain well-formed (201 + correct envelope + valid `data.id`).

## Step 8: Finalize PRD — 2026-06-15T00:46:00.000Z

Ran (skip condition not met: Step 7 applied 3 implementation fixes). **PRD.md vs PRD_FINALIZED.md: 299 vs 299 lines — 0 lines changed, 0.0% delta (byte-identical).**

**Changes made:** None. All three Step 7 fixes are transport/boot hardening with explicitly zero impact on any PRD-defined response body, status code, error_id, or domain semantic — none pins a PRD-left-open *behavioral* choice and none mismatches the PRD, so none warrants a PRD edit:
- `socket.getfqdn` override (app.py:17-28) — cosmetic startup-banner hostname only; server still binds 0.0.0.0; responses identical. PRD silent on banner/DNS.
- `debug=False, use_reloader=False` (app.py:1315-1321) — prevents reloader double-fork; no effect on request handling/response/semantic.
- `@app.after_request` → `Connection: close` (app.py:70-73) — HTTP transport framing only; JSON envelope/status/semantics unchanged. PRD's only header discussion is request-side `X-User-ID`/`X-User-Role` (§2.1).

Pre-edit no-edit gate applied to each item (grep of PRD.md for fqdn/hostname/banner/socket, reloader/debug, connection/keep-alive/header → only the unrelated §2.1 auth-header line). No PRD prose describes any of these; nothing to pin.

## Step 9: Complete PRD — 2026-06-15T00:52:00.000Z

Full PRD-vs-implementation scan from `PRD_FINALIZED.md`. **PRD_FINALIZED.md 299 lines / 41,919 chars → PRD_COMPLETED.md 299 lines / 43,883 chars (char-delta +1,964).** 11 paragraphs revised in place, no new sections/lines.

**Counts:** 12 ambiguity-pins, 1 mismatch-revision (13 changes total — but 2 were revise-mismatch on ordering; listing below).

**Changes** (`section — kind — class — what — impl ref`)
- §3.1 — insert — ambiguity — Park logical clock defaults to park's creation instant until first set — app.py:169,175-176; services.py:32-34
- §3.2 (close) — insert — ambiguity — Seat-consuming write against CLOSED slot rejected with ERR_SLOT_CAPACITY_EXCEEDED, after version check — app.py:527-528,1087-1088
- §3.2 (sweep) — insert — ambiguity — Sweep before slot ends_at rejected with ERR_INVALID_STATE; version/updated_at bump only when ≥1 pass actually swept — app.py:284-301
- §3.6 (pay) — insert — ambiguity — UNPAID-but-CANCELLED/NO_SHOW pass rejected ERR_INVALID_STATE (UNPAID check precedes cancelled/no-show check) — app.py:596-599
- §3.6 (check-in) — revise — mismatch — Four check-in requirements re-stated as ordered sequence state→waiver→window→paid — app.py:622-637
- §3.6 (complete) — insert — ambiguity — Pass completion increments slot version by 1 — app.py:657
- §3.6 (cancel) — insert — ambiguity — Pass cancellation increments slot version by 1 — app.py:684
- §3.7 (tiers) — insert — ambiguity — member_id resolves to member's most recently created membership — services.py:70-77
- §3.7 (renewal) — insert — ambiguity — FAILED renewal from PAST_DUE → ERR_INVALID_STATE; PAST_DUE renewal exempt from due-date check — app.py:844-851
- §3.8 (hold-deposit) — revise — mismatch — Hold-deposit checks re-stated in impl order state→room-conflict→version→capacity — app.py:1071-1090
- §3.9 (filing) — insert — ambiguity — Filing against non-CHECKED_IN pass → ERR_INVALID_STATE — app.py:1225-1226
- §3.9 (filing) — revise — ambiguity — reviewed_by_user_id is null (not "empty") until reviewed — app.py:1235

**Left unchanged** (already pinned or covered by generic rules): cancel/complete/confirm + party-transition legality errors under §2.7 ERR_INVALID_STATE catch-all; manual-close + SEVERE-cascade version bumps under §2.4 derived-field rule; numeric >=0 field validations under §2.7 ERR_VALIDATION catch-all; set_clock optional park_id (single-park model).

---

## Pipeline Complete — 2026-06-15T00:52:00.000Z

Final state: **8/8 rounds 76/76 passing**. All artifacts present: SCAFFOLD.yaml (+DIFFICULTY/CORNER design), PRD.md / PRD_FINALIZED.md / PRD_COMPLETED.md, test_helpers/ (9 files), test_suite/ (76 tests across 6 files + conftest), workspace/implementation/ (10 source files + start.sh), results.{1..8}.json all green.
