# Worklog — task_0161_salon_spa_booking

## Step 1: Create task directory — 2026-06-05T00:00:00.000Z

Created `tasks/task_0161_salon_spa_booking/` and `tasks/task_0161_salon_spa_booking/workspace/` (pre-assigned path; auto-index scan overridden per orchestrator directive). Verified `./INSTRUCTION.md` present for Step 3 copy.

## Step 2: Generate scaffold (Expert tier) — 2026-06-05T01:18:00.000Z

All assertion literals confirmed correct. The scaffold package is complete and passes every check.

Generated all three scaffold artifacts for `task_0161_salon_spa_booking` (Expert tier). `scaffold_lint.py` reports VERDICT: clean lint (472 calls scanned across §1.8+§1.9, 0 violations). All grounds references resolve, names are unique across both design files, no forbidden concurrency vocabulary, file-split honored, and all formula-derived assertion literals were computed in code.

Complexity profile: temporal_windowing (primary) + pricing_engine (secondary); layers optimistic_concurrency / cascading_side_effects / rate_threshold_triggers / derived_field_reconciliation; flat topology; branching state machines; peer_roles; immediate consistency.

Entities (13): Salon, Stylist, Resource, Service, Client, MembershipPlan, Membership, Package, PackagePurchase, Appointment, ProductSku, Checkout, ProductSale

Counts:
- State machines: 3 (Appointment branching, Checkout SETTLED→VOIDED compensation, Membership ACTIVE↔PAST_DUE cycle)
- Calculations: 6 (appointment_service_quote, stylist_service_earning, service_revenue_recognized, package_session_value, tip_distribution, retail_line_total)
- Validations: 15 (priority-ordered)
- Endpoints: 49
- Errors: 17
- Roles: 4 (SalonOwner, FrontDesk, Stylist, Client)
- Concurrency rules: 2 (OCC on Stylist.version for booking, Salon.version for clock advance)

§1.8 Difficulty Design: all 9 rule_ids present, 2 instances each = 18 total, each meeting its §0.5 differentiation clause (dual-variant on Stylist-payout vs Appointment-quote domains; combinatorial modes (b) per-line rounding + (a) ≥3-input min-clamp; non-linear shapes on Appointment branch + Membership cycle; depth-3 no-show→strike→suspend and depth-2 void→reclassify→strike cascades; two distinct validation-priority error-category pairs; boundary precision on resource-adjacency vs strike-threshold; cross-entity deps Appointment→Client and Appointment→Membership; overlap with buffer-padded vs bare half-open semantics on Stylist vs Resource; conserved-quantity invariants over inventory units vs package sessions).

§1.9 Corner Design: 40 active instances + 8 `excluded_because` stubs = 48 total, spanning entities(10), state_machines(8), calculations(7), validations(6), endpoints(3), errors(6), rbac(4), cross_cutting_complexity_layers(3), consistency_model(1).

Structural note for downstream: flat top-level URL paths (e.g. `/stylists`, `/appointments`) with `salon_id` as a body/filter field rather than nested `/salons/{sid}/...`, because the lint's FK reverse-reachability check (f) only resolves collection segments for top-level paths; the salon-scoped clock endpoint remains path-addressed as `POST /salons/{id}/_clock/advance` since the Salon is its OCC parent.

## Step 3: Copy INSTRUCTION.md — 2026-06-05T01:18:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0161_salon_spa_booking/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-05T01:22:00.000Z

Output: `workspace/PRD.md` (~261 lines / 260 actual).

Section list:
- §1 Introduction — 3 paragraphs (system goals + pain points, checkout-as-ledger framing, units note: money in integer cents, durations in minutes)
- §2 Global Specifications — 9 subsections: 2.1 RBAC (all 4 roles, entity_backed + opaque identities), 2.2 API Response Structure (verbatim match), 2.3 Pagination, 2.4 Common Resource Properties + Versioning (ProductSale common_fields:false called out), 2.5 Simulated Clock + Temporal Evaluation, 2.6 Precision and Rounding, 2.7 OCC (both rules), 2.8 Resource Resolution + Tenant Scoping (left-to-right + cross-aggregate), 2.9 Validation Ordering
- §3 Business Logic & Workflows — 7 subsections: 3.1 Configuring Salon+Catalog, 3.2 Clients/Memberships/Packages, 3.3 Booking (8-step priority check cascade + quote/deposit snapshot calc), 3.4 Confirm/Cancel/No-Show (depth-3 suspend cascade + dispute), 3.5 Checkout (6 money fan-outs), 3.6 Voiding, 3.7 Reading the Ledger
- §4 Endpoint Definitions — 4-column table, all 49 endpoints
- §5 Error Code Catalogue — 2-column table, all 17 errors

Hard Contract reports:
- Contract 1 — Field-Name Coverage: 65 required tokens, 0 missing. PASS
- Contract 2 — Rule Coverage: 2/2 OCC rules, all Appointment+Checkout+Membership transitions with preconditions→error_ids, all 6 calculations with pinned rounding + worked examples (commission 4000/6000, booth 8500/1500, pooled 334/333/333), all 15 validations matched to error_ids with explicit booking priority chain first→eighth, void + no-show cascades enumerated. PASS
- Contract 3 — §3 Path Purity: 360 backtick tokens scanned, 0 slash-paths, 0 bare methods, 0 method+path. PASS

Notable scaffold→prose decisions: §3 uses pure state-transition/role+action framing (no paths); booking validation order made explicit first…eighth; tip POOLED algorithm rendered with pinned order (floor share, leftover cents to earliest created_at, id never tiebreaker; worked 1000/3 example); half-open interval semantics for stylist (buffer-padded) + resource (bare), boundary-touching allowed; ProductSale missing updated_at/version called out; no-show depth-3 cascade + void compensating transition fully enumerated. Difficulty/Corner design files NOT opened; no sibling tasks consulted.

## Step 5: Generate unit tests — 2026-06-05T01:42:00.000Z

Test files: 5 (`test_suite/test_01_catalog_and_entities.py` … `test_05_compensating_and_concurrency.py`) plus `test_suite/conftest.py`.

Total tests: 76, all collect cleanly under pytest.

Per-queue counts (Design tags):
- Queue A (Difficulty): 36 tags across all 18 difficulty instances (9 rules × 2) — every instance covered by ≥2 tests ✓
- Queue B (Corner): 40 tags across all 40 non-stub corner instances — every instance covered by ≥1 test ✓
- Per-file: test_01=14, test_02=20, test_03=19, test_04=15, test_05=8.

Instances skipped: None of the testable instances were skipped — every non-stub instance in both indices passed the PRD-first two-condition filter (the PRD prose verbatim-states each rule, including the explicit §3.3 booking validation-priority ordering and §2.6/§3.5 pinned rounding orders). The 8 `excluded_because:` corner stubs correctly NOT translated.

test_helpers files produced (9): `__init__.py` (barrel), `types.py` (entity TypedDicts/enums; ProductSale carries only id/created_at), `api_client.py` (one method per endpoint), `api_errors.py` (17 error IDs + HTTP map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque SalonOwner/FrontDesk constants + entity-backed make_stylist_headers/make_client_headers builders), `fixtures.py` (composite tiers). All files byte-compile; 76 tests collect; every test carries exactly one Design: tag; no skip/skipif/xfail; no scaffold leak; all 111 quoted PRD fragments verbatim-present.

## Step 6: Generate implementation — 2026-06-05T01:42:30.000Z

File list under implementation/: start.sh, requirements.txt (flask==3.0.3), app.py, db.py, errors.py, response.py, util.py, validate.py, lookups.py, middleware.py, calculations.py, cascades.py, routes/ (__init__.py, common.py, + one per entity: salons, stylists, resources, services, clients, membership_plans, memberships, packages, package_purchases, product_skus, appointments, checkouts, product_sales).

Storage: in-memory only, 13 module-level dicts in db.py keyed by UUID. Nothing seeded at import or boot (GET /stylists returns total_count:0 on boot). Module-level monotonic _seq counter (reset per process) for deterministic intra-ms tiebreak on created_at and pooled-tip ranking.

start.sh: set -euo pipefail, cd to script dir, guarded pip install (if ! python3 -c "import flask"), then exec python3 app.py. app.py reads PORT (default 10000), app.run(host="0.0.0.0", port=PORT) foreground. Verified PORT=10233 bash start.sh responded on 0.0.0.0:10233.

Notable PRD→code decisions: envelope per §2.2 (meta{api_request_id, api_request_timestamp} + response_type + data; pagination fields injected into meta for lists); money via Decimal+ROUND_HALF_UP; pinned eval orders verbatim (package value divide-then-round-once; retail round-per-line-then-sum; commission round stylist share then salon=remainder; pooled tip floor-then-distribute remainder cents by created_at ASC, id never tiebreaker); booking 8-step domain check order (§3.3); two OCC fields (expected_stylist_version on booking, expected_salon_version on clock advance, 412 mismatch); cascades depth-3 (wallet forfeit/refund → strike++ → conditional auto-suspend, single Client version bump per batch); void reclassifies completed visit to NO_SHOW restoring inventory+package sessions with booking-snapshotted deposit_held_cents; entity-backed ownership (Client self-only book/cancel/purchase, ERR_FORBIDDEN before existence/state); ProductSale only id+created_at (§2.4); clock-advance temporal checks read salon's simulated current_utc.

## Step 7: Test and iterate to green — 2026-06-05T02:05:00.000Z

All 8 parallel rounds pass 76/76. Final summary below.

**Iterations run:** 2 (initial diagnostic sweep + 1 fix-and-verify sweep). Final sweep: all 8 parallel rounds green, 76/76 each.

**Initial state:** 6 tests failed consistently in all 8 rounds: `test_appointment_end_utc_computed_from_duration`, `test_stylist_buffer_padded_gap_allows_booking`, `test_appointment_branches_cancel_vs_noshow_divergent_effects`, `test_cancel_conserves_package_sessions`, `test_noshow_conserves_package_sessions`, `test_second_checkout_already_checked_out`.

**Tests deleted:** None. All 6 failures were PRD-covered + uniquely-derivable; each traced to either a test-artifact bug or an implementation bug.

**Fixes applied to `test_suite/` (STEP 2 — test-vs-PRD consistency):**
- `test_01_catalog_and_entities.py` — `test_appointment_end_utc_computed_from_duration`: assertion compared an exact string spelling (`...:00Z`) of a computed timestamp whose serialization format PRD §2.4 governs as three-fractional-digit ISO 8601 (impl emits `...:00.000Z`). PRD pins the *instant* (start+45min), not the spelling. Replaced the exact-string compare with an instant compare via a new `_parse_iso_instant` helper (partial-coverage split: kept the value assertion, dropped the under-determined format assertion).
- `test_02_booking_validations.py` — `test_stylist_buffer_padded_gap_allows_booking`: fixture used `start=13:40`, which with duration 30 + buffer 10 pads to `[13:30,14:20)` and overlaps the first appointment's `[12:50,13:40)` — so the PRD-faithful impl correctly rejected. Changed start to `13:50` so the two padded half-open intervals merely touch at 13:40 (the "touch-at-boundary allowed" rule the test means to assert).
- `test_03_appointment_lifecycle.py` — `test_appointment_branches_cancel_vs_noshow_divergent_effects`: fixture booked the *same* stylist twice at 13:00 (one stylist cannot serve two clients at once → correct `ERR_STYLIST_DOUBLE_BOOKED`). Added a second stylist so the two concurrent 13:00 appointments land on distinct schedules.
- `test_05_compensating_and_concurrency.py` — `test_noshow_conserves_package_sessions`: the 14:00 `advance_clock` return was discarded, so the later 16:30 advance carried a stale `expected_salon_version` → `ERR_STALE_SALON_VERSION`. Reassigned `salon = advance_clock(...)` to thread the version (PRD §2.7). Also corrected the misleading "restores its held session" comments in both package-conservation tests (the appointments were never checked out, so nothing is redeemed/restored).

**Fixes applied to `implementation/` (STEP 3):**
- `routes/appointments.py` (`book`, `cancel`, `no_show`) + `routes/checkouts.py` (`create_checkout`, `void_checkout`) + `util.py`: added an internal `_session_redeemed` flag (stripped from public output). Cancel/no-show previously restored a package session unconditionally whenever `package_purchase_id` was set, over-crediting appointments that were never checked out (PRD §3.5: a session is redeemed only at checkout; cancel/no-show act only on BOOKED/CONFIRMED, which never redeemed). Now cancel/no-show restore only when `_session_redeemed` is set (it never is for them), checkout sets it on redeem, and void restores+clears it — keeping the §3.6 void path correct (verified void still restores a redeemed session).
- `routes/checkouts.py` (`create_checkout`): moved the settled-checkout existence check *before* the generic state check, so a second checkout of an already-settled appointment returns `ERR_ALREADY_CHECKED_OUT` (PRD §3.5's specific second-checkout clause) rather than the generic `ERR_INVALID_STATE`. CANCELLED/NO_SHOW (no settled checkout) still return `ERR_INVALID_STATE`.

**Orchestrator verification:** result files were cleaned by the subagent's per-sweep `rm`; orchestrator re-ran the full 8-round parallel sweep independently — all 8 rounds passed=76 total=76 failed=0. `results.{1..8}.json` persisted under `workspace/implementation/`.

## Step 8: Finalize PRD — 2026-06-05T02:18:00.000Z

Line counts: PRD.md = 260 lines; PRD_FINALIZED.md = 260 lines; %-delta = 0% (both edits are in-line revisions of existing lines; no lines or sections added/removed). Two of 260 lines changed (~0.77% of lines touched).

Changes (one bullet each):
- §3.3 — insert — pinned the serialization format of the computed `end_utc` field as ISO 8601 UTC with three fractional digits and a trailing `Z` (per the §2.4 convention), which PRD left open — `implementation/routes/appointments.py:156`
- §3.5 — revise — made the already-settled-checkout check take precedence over the state/timing checks, and corrected the misleading "(for instance one already completed)" example: a completed appointment always has a settled checkout and so returns `ERR_ALREADY_CHECKED_OUT`, while `ERR_INVALID_STATE` is for states with no settled checkout (`CANCELLED`/`NO_SHOW`) or a pre-start attempt — `implementation/routes/checkouts.py:53-69`

Items in <step_7_diff> that produced NO PRD edit (and why):
- `test_appointment_branches_cancel_vs_noshow_divergent_effects`, `test_stylist_buffer_padded_gap_allows_booking` — pure test-fixture bugs (double-booked stylist / overlapping padded interval); PRD §3.3 already fully determines the behavior verbatim. No silence, no mismatch.
- `test_cancel_conserves_package_sessions`, `test_noshow_conserves_package_sessions` (the `_session_redeemed` impl fix) — PRD §3.2/§3.4/§3.5 already correctly and verbatim state that a session is redeemed only at checkout and restored on cancel/no-show/void only "if the appointment had redeemed a package session." Step 7 fixed the impl to match the already-correct PRD; `_session_redeemed` is an internal mechanism with no PRD-visible surface. No edit needed.

Per-edit pre-edit search log:
- Edit 1 (§3.5 — checkout eligibility ordering): (a) precedence between ERR_ALREADY_CHECKED_OUT and ERR_INVALID_STATE on checkout creation + triggering state landscape. (b) Enumerated routes/checkouts.py:43-69 (create_checkout, only checkout-creating entry), _has_settled_checkout (36-40), completion (126-151: COMPLETED only ever set with a SETTLED checkout), void_checkout (181-217: leaves NO_SHOW + VOIDED, no settled checkout); grep confirmed no other producer. (c) Stated already-settled check fires "regardless of state," scoped ERR_INVALID_STATE clause to "only when no settled checkout exists" with qualifying example states CANCELLED/NO_SHOW (replaced false "already completed" example), preserving pre-start timing case — consistent with VOIDED re-checkout path.
- Edit 2 (§3.3 — end_utc serialization format): (a) serialized spelling of computed end_utc. (b) Enumerated routes/appointments.py:156 (end_utc = strftime + millis(3) + Z); 122,131 (read back via parse_dt, format-agnostic); 155 (start_utc stored as raw client input, echoed NOT normalized); routes/salons.py:38,67 (current_utc echoed raw); response.py:23-26 now_iso() (three-digit Z, §2.4). (c) Scoped the format claim strictly to computed end_utc (avoided "all timestamps" generalization) since start_utc and post-advance current_utc are echoed raw and could carry a different spelling — a universal claim would have been a brand-new mismatch.

## Step 9: Complete PRD — 2026-06-05T02:28:00.000Z

Source vs completed: PRD_FINALIZED.md = 260 lines / 43,912 chars; PRD_COMPLETED.md = 260 lines / 45,033 chars; char delta +1,121 (line count unchanged; all edits in-paragraph inserts/revisions, no new sections or paragraphs).

Counts: 6 changes total — 4 ambiguity-pins, 2 mismatch-revisions.

Per-change:
- §2.4 Common Resource Properties & Versioning — insert — ambiguity — pinned the `version` initial value as 1 (PRD said only "its initial value") — `implementation/util.py:44`
- §2.8 Resource Resolution & Tenant Scoping — revise — mismatch — PRD claimed checkout retail SKUs are "resolved the same way" (tenant-scoped); impl resolves caller-supplied retail-line SKUs by existence only, no salon re-scope — `implementation/routes/checkouts.py:94-96`
- §3.2 Clients, Memberships, and Packages — insert — ambiguity — pinned that GET /clients omits ARCHIVED by default and includes them only when filtered status=ARCHIVED, and that the list accepts salon_id/status filters — `implementation/routes/clients.py:75-81`
- §3.3 Booking an Appointment — insert — ambiguity — pinned that booking only earmarks/validates a package session and does not decrement sessions_remaining; decrement (redemption) happens at checkout, so a pre-checkout cancel/no-show restores no session — `implementation/routes/appointments.py:160-163,241,267` + `implementation/routes/checkouts.py:146-148`
- §3.3 Booking an Appointment — insert — ambiguity — pinned that caller-supplied start_utc is stored/echoed verbatim (not re-serialized to three-fractional-digit form), with only its parsed instant used for temporal checks — `implementation/routes/appointments.py:155`
- §4 Endpoint Definitions — revise — mismatch — PRD grouped "checkout" under 200 OK modify ops; impl returns 201 Created for POST /checkouts (a create) and 200 OK only for checkout void — `implementation/routes/checkouts.py:154` (create→201) vs `:217` (void→200)

Calculation-heavy §3.5 (per-session value divide-then-round-once, commission/booth-rent split with revenue clamp, pooled-tip created_at ranking with id never tiebreaker, per-line retail rounding) verified against `calculations.py` — already pinned uniquely, no change. Validation-ordering spine (§2.9), OCC guards (§2.7), booking eight-step order (§3.3) already match impl.

## Pipeline complete — 2026-06-05T02:28:30.000Z

All 9 steps done. Final state: 76/76 tests pass across 8 parallel stability rounds (independently re-verified by orchestrator). Artifacts present: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/ (9 files), test_suite/ (5 test files + conftest), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}, results.{1..8}.json (all passing).
