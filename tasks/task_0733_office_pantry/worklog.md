# Worklog — task_0733_office_pantry

## Step 1: Create task directory — 2026-07-04T11:05:39.000Z

Created `tasks/task_0733_office_pantry/` and `tasks/task_0733_office_pantry/workspace/`. Scenario: Office-Pantry & Snack Subscription Service (SnackNation style). Difficulty: Expert (passed to scaffold-generator in Step 2 only).

## Step 2: Generate Scaffold — 2026-07-04T15:05:41.000Z

VERDICT: clean lint. All acceptance criteria are met.

result: Wrote three scaffold artifacts to `/home/ubuntu/github/CodingPRD/tasks/task_0733_office_pantry/` for the Office-Pantry & Snack Subscription Service (Expert difficulty). SCAFFOLD.yaml has 12 entities, 54 endpoints, 25 error codes, 3 roles, 4 state machines, 6 calculations, 23 ordered validations, and 1 OCC concurrency rule. SCAFFOLD_DIFFICULTY_DESIGN.yaml has 18 instances (2 per rule × 9 §0.5 rules) covering dual-variant calcs on Delivery (cost) + Client (satisfaction) domains, mode-a + mode-b combinatorial formulas, cyclic (Subscription) + parallel (Invoice) non-linear machines, depth-3+ pause cascade + depth-2 dispute-credit cascade, state/referential + safety/constraint priority pairs, headcount threshold + 24h schedule boundary precision, Delivery↔Subscription + RC↔Delivery cross-entity dependencies, 24h buffer + half-open disjointness temporal-overlap semantics, and money + time compensating invariants. SCAFFOLD_CORNER_DESIGN.yaml has 27 active corners + 4 excluded_because stubs spanning entity creation/defaults/system-fields, invalid transitions, conditional cascade filtering, formula boundary/branch coverage, RBAC/ownership denials, pagination, OCC 412, version bump, and overdue-invoice sweep. `python3 scaffold_lint.py` prints `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` after 411 calls scanned.

Files:
- /home/ubuntu/github/CodingPRD/tasks/task_0733_office_pantry/SCAFFOLD.yaml
- /home/ubuntu/github/CodingPRD/tasks/task_0733_office_pantry/SCAFFOLD_DIFFICULTY_DESIGN.yaml
- /home/ubuntu/github/CodingPRD/tasks/task_0733_office_pantry/SCAFFOLD_CORNER_DESIGN.yaml

## Step 3: Copy INSTRUCTION.md — 2026-07-04T15:05:53.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `tasks/task_0733_office_pantry/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-04T15:13:10.000Z

All three hard contracts pass. Now updating the task list and writing the summary.

**Hard Contracts final status:**

```
Contract 1 — Field-Name Coverage:
- entities[].fields + endpoints[].input tokens: 63 required, 63 present, 0 missing
Status: PASS  (added `subscription_id` prose mention in §3.4 after audit)

Contract 2 — Rule Coverage:
- validations[] priority: 23 checked, 23 expressed as ordered enumeration in §2.11, 0 missing
- concurrency_rules[] OCC rejection: 1 checked (subscription-create-stale-client), 1 expressed (write_endpoint=subscription-create + expected_client_version + ERR_STALE_CLIENT_VERSION + HTTP 412 all named in §2.8), 0 missing
- state_machines[].transitions: 4 machines × 15 transitions total checked, all fully expressed with preconditions + side_effects (§3.3, §3.4, §3.5, §3.6, §3.7), 0 missing
- calculations[]: 6 checked (delivery_provisional_charge, delivery_final_charge, subscription_fee, invoice_consumption, par_projection, client_satisfaction_score) — all expressed in precise prose with constants (BULK_UNITS_THRESHOLD=100, BULK_LINE_DISCOUNT_PCT=0.05, NEUTRAL_SCORE=3.00, weights 1/2, round-half-up ordering), no pseudocode, 0 missing
- validations[] conditions: 23 checked, each matchable to its error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: dietary applies to both par-levels and feedback (§3.2 and §3.8), pause cascade applies to OPEN cycle + SCHEDULED/EN_ROUTE deliveries + EN_ROUTE-only client credit (§2.7, §3.3), 0 missing
- entities[].fields[] structured content: 63 field defaults, initial values, and enum sets reconstructible from prose, 0 missing
- sibling-branch symmetry: provisional/final variants, PER_EMPLOYEE/FLAT branches, SCHEDULED/EN_ROUTE cascade cancels, provisional/authoritative satisfaction variants — all rendered with equal density
Status: PASS

Contract 3 — §3 Path Purity:
- backtick tokens scanned in §3
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**PRD summary (for orchestrator worklog):**

- File: `/home/ubuntu/github/CodingPRD/tasks/task_0733_office_pantry/workspace/PRD.md`
- 374 lines, ~7,500 words
- Structure: §1 Introduction (2 paragraphs) → §2 Global Specifications (11 subsections: RBAC, response envelope, pagination, common resource properties, nested retrieval, monetary precision, hierarchical consistency/cascades, OCC, dietary/refrigeration safety, capacity/scheduling, priority-ordered validation catalog) → §3 Business Logic (8 subsections: catalog & onboarding, assortment, subscription lifecycle, rotation cycles & delivery generation, fulfillment, disputes & credit, close & invoicing, feedback & satisfaction) → §4 endpoint table (4 cols, 52 endpoints) → §5 error catalog (2 cols, 25 errors)
- Notable design choices: (1) §2.11 promoted the 23-priority validation ordering to a single ranked list rather than scattering — the ordering is itself a rule the tests will assert; (2) §2.7 states the depth-4 cascade invariant abstractly and §3.3 re-walks it in narrative for redundant reinforcement; (3) the four-regime interaction (`MICRO_MARKET` × 100-unit bulk boundary) is spelled out in §3.5 with the "each rounded independently" per-line rounding rule; (4) subscription-fee rounding order (discount → round → add base) is pinned in both §2.6 and §3.7 to match the scaffold's scaffold-pins comment; (5) the parallel Invoice dimensions (`payment_status` vs. `dispute_status`) are called out explicitly in §3.7 to prevent implementers from collapsing them; (6) §2.8 keeps OCC framed strictly as stale-version, never "simultaneously" / "race".

result: PRD.md generated (374 lines, 7,500 words, 11 §2 subsections, 8 §3 subsections) with all three hard contracts PASS at `/home/ubuntu/github/CodingPRD/tasks/task_0733_office_pantry/workspace/PRD.md`.

## Step 5: Generate Unit Tests — 2026-07-04T15:40:35.000Z

result: Generated Stage 1 (`test_helpers/`, 9 modules, 1197 lines) and Stage 2 (`test_suite/`, 7 test files + conftest, 62 tests, 1691 lines) for task_0733_office_pantry.

Worklog summary (verbatim for orchestrator):

```
=== Step 5 tests generated for task_0733_office_pantry ===

Stage 1: test_helpers/  (9 files, ~1200 lines)
  types.py           TypedDicts for all 12 entities; common_fields=false variants
                     (Preference, Feedback) correctly omit updated_at/version.
  api_client.py      52 endpoint methods extending GenericApiClient.
  api_errors.py      25 ApiErrorId enums + HTTP_STATUS_CODES registered with framework.
  assertions.py      Per-entity assertions + assert_delivery_money_conservation.
  factories.py       11 payload factories, input-only fields.
  constants.py       Domain thresholds (BULK_UNITS_THRESHOLD=100, etc.).
  test_users.py      Opaque PlatformAdmin + entity-backed builders
                     (make_client_admin_headers, make_location_manager_headers).
  fixtures.py        Primitive helpers + composite fixtures:
                     setup_active_subscription (canonical 8-call composite),
                     setup_scheduled_delivery, setup_en_route_delivery,
                     setup_delivered_delivery, setup_disputed_delivery,
                     report_all_actuals_and_resolve, close_and_get_invoice.
                     Identity threading enforced: every entity_backed call routed
                     via make_*_headers(entity_id).
  __init__.py        Barrel export of framework + PRD-specific symbols.

Stage 2: test_suite/  (7 files, 62 tests)
  conftest.py                          pytest bridge, 3 role fixtures.
  test_01_crud_and_lookup.py           10 tests - Corner entities/rbac/endpoints basics.
  test_02_state_machines.py             8 tests - Diff rule 3 + Corner state_machines.
  test_03_validations_and_errors.py    10 tests - Diff rule 5 + Corner validations.
  test_04_calculations_and_pricing.py  11 tests - Diff rule 1, 2 + Corner calculations.
  test_05_cascades_and_workflows.py     8 tests - Diff rule 4, 7 (cascades, cross-entity).
  test_06_boundaries_and_temporal.py    8 tests - Diff rule 6, 8 (inclusive thresholds,
                                                  min-gap, half-open windows).
  test_07_invariants_and_occ.py         7 tests - Diff rule 9 + Corner cross_cutting.

Coverage audit:
  Difficulty index: 18/18 non-stub instances covered by >=2 tests each.
  Corner index:     26/27 non-stub instances covered by >=1 test each.
                    Stubs (4): not translated (verified difficulty_instance pointers resolve).

Skipped (Silence pattern: default-value):
  Corner/entities/product_dietary_flags_default_empty_array
    - PRD §3.1 names dietary_flags as an "array of dietary attribute strings" but does
      not state the server-side default when omitted. Two PRD-only readers could
      faithfully ship null OR []; asserting either would leak scaffold's `default: []`.
    - Documented in test_01_crud_and_lookup.py module docstring.

No @pytest.mark.skip / skipif / xfail markers anywhere in test_suite.
Every test docstring carries a verbatim PRD citation (C1/C2/C3) + a "Design: <queue>/<...>"
line (C4) resolving to a real instance name in the corresponding yaml.
All 17 generated files pass ast.parse syntax check.
```

Files at:
- `/home/ubuntu/github/CodingPRD/tasks/task_0733_office_pantry/test_helpers/` (9 files)
- `/home/ubuntu/github/CodingPRD/tasks/task_0733_office_pantry/test_suite/` (8 files including conftest.py)

## Step 6: Generate Implementation — 2026-07-04T15:40:35.000Z

Ready in 2 seconds, well under the 60s window. Empty store on fresh boot (no seeding), consistent with the spec.

---

Implementation summary for the worklog:

**Files at `/home/ubuntu/github/CodingPRD/tasks/task_0733_office_pantry/workspace/implementation/`:**
- `start.sh` — foreground launcher, guards `pip install -r requirements.txt` on cheap `import flask` probe, `exec python3 app.py`.
- `requirements.txt` — `Flask==3.0.3`.
- `app.py` (~1200 LOC) — all endpoint handlers + error handlers + Flask app registration.
- `services.py` — serialization, existence/ownership checks, calculations (provisional/final charge, subscription fee, dispute credit, consumption, satisfaction), cascade helpers (`invalidate_rotation_cycle`, `cancel_delivery_scheduled/en_route`), assortment projection, half-open interval overlap, pagination.
- `db.py` — in-memory `Store` (dicts keyed by id) + logical clock (`_clock_iso`, default `2026-03-01T00:00:00Z`) + `parse_iso`/`iso_from_datetime` helpers.
- `middleware.py` — `require_auth(allowed_roles)` extracts `X-User-Role`/`X-User-ID`, raises `ERR_MISSING_AUTH_HEADERS` / `ERR_UNAUTHORIZED`.
- `response.py` — envelope builders producing `{meta:{api_request_id, api_request_timestamp, [limit/offset/total_count/has_more]}, response_type, data}` per PRD §2.2.
- `errors.py` — `ApiError(error_id, http_status, message)` custom exception.

**Endpoints implemented (all 50+ from the endpoint table):** Plans, Products, Clients (+ headcount patch), Locations, Preferences, ParLevels, Subscriptions (+ activate/pause/resume/cancel), RotationCycles (+ close, generate deliveries, list), Deliveries (+ dispatch/confirm/dispute/resolve-dispute/finalize), DeliveryLines (+ actuals patch), Invoices (+ pay, resolve-dispute), Feedback, satisfaction score, `_clock/set_current_utc`, `_system/advance-invoice-default`.

**Notable design choices:**
- Response envelope uses `meta`/`response_type`/`data` exactly as scaffold+PRD §2.2 specifies; timestamps are ISO 8601 UTC with 3 fractional digits + `Z`.
- Auth: single `X-User-Role`/`X-User-ID` scheme; `PlatformAdmin` opaque id, `ClientAdmin` id=Client.id, `LocationManager` id=Location.id.
- All monetary calc uses `decimal.Decimal` with `ROUND_HALF_UP`; per-line fee and per-line discount each rounded independently before per-line sum, per PRD §2.6. Subscription-fee follows discount-then-round-then-add ordering.
- Logical clock: `POST /_clock/set_current_utc` mutates in-memory ISO string; `STORE.now()` returns a UTC datetime used for `created_at`/`updated_at`/`paused_at`/`dispatched_at`/etc.
- Cascade `_pause_or_cancel_from_active` implements the 4-hop chain (Sub → RC OPEN→INVALIDATED → SCHEDULED/EN_ROUTE Deliveries → Client credit for EN_ROUTE only) plus the parallel invoice CLEAN→UNDER_DISPUTE fan-out.
- OCC only on `POST /clients/{id}/subscriptions` with `expected_client_version` (priority 23, after headcount floor).
- No entity seeding at startup — store starts empty on every boot; tests build state via API.
- Validation priority order followed strictly (auth → existence → ownership → state → cross-entity state → business_safety → business_constraint → business_temporal → business_referential → business_fiscal → OCC).
- Half-open interval overlap `a<d && c<b` for rotation cycle overlap and out-of-window deliveries; buffer semantics `<24h` rejected for delivery scheduling (exactly 24h allowed).
- Satisfaction score: authoritative (default) filters feedback to products in the client's ParLevels; provisional counts all client feedback; weight 2 when swap suggestion present else 1; empty set → 3.00 neutral; rounded half-up to 2 dp.

**Verified via smoke test:** create plan/client/location/product/par-level (with 150-unit line at MICRO_MARKET), create+activate subscription, open first rotation cycle, generate delivery, dispatch (provisional_cents=45000: 150×300 raw + 2250 fee - 2250 bulk discount), pause cascade correctly flips RC→INVALIDATED, delivery→CANCELLED with dispute_credit=45000, client.credit_balance_cents=45000. Cold-boot ready in 2s.

result: Python+Flask implementation for task_0733_office_pantry written to workspace/implementation/ (start.sh + 7 py files); boots cold in ~2s, empty in-memory store, envelope/errors/RBAC/cascade/OCC/calculations verified via smoke test.

## Step 7: Iterate to Green — 2026-07-04T15:49:22.000Z

All 8 rounds green: 62/62 passed. Sanity check the task list state and emit summary.

**Sanity check:** All 8 parallel rounds reported `passed=62, total=62, failed=0, errors=0`. Union failure set is empty. The two fix categories addressed exactly the two failure signatures observed in the initial sweep (5 tests failing in every round).

**Summary:**

- **Iterations run:** 2 sweeps (initial 5/62 failing → clean 62/62).
- **Tests deleted:** none.
- **Fixes applied to `test_suite/`:**
  - `test_suite/test_01_crud_and_lookup.py` line 184 — `test_satisfaction_returns_neutral_when_no_feedback` used variant token `"authoritative_stocked_feedback"` (scaffold-verbatim, not PRD-attested); PRD §3.8 only bolds the phrase "authoritative variant". Retokened to `"authoritative"` (STEP 2 test-request bug: scaffold leak into request payload).
  - `test_suite/test_04_calculations_and_pricing.py` lines 138 and 157 — same scaffold-leak in `test_authoritative_variant_excludes_unstocked_product_feedback` and `test_provisional_variant_counts_unstocked_product_feedback`. Retokened to `"authoritative"` and `"provisional"`.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `implementation/`:**
  - `workspace/implementation/services.py` — `rotation_cycle_overlaps_existing` now skips `INVALIDATED` and `CLOSED` rotation cycles when computing overlap. Without this, pause→resume is structurally impossible: pause invalidates the OPEN cycle but leaves its `[effective_from, effective_to)` span in the store, so resume's new window (whether same-instant or later) always overlaps the invalidated-but-not-forgotten span and returns `ERR_ROTATION_CYCLE_OVERLAP`. PRD §3.3 states explicitly: "The invalidated cycle is not resurrected; the new cycle is a fresh window." — uniquely derivable that terminal cycles cannot gate future ones, otherwise resume never works.

result: 8-round parallel sweep clean at 62/62 passed on every round; 5 originally-failing tests fixed via 1 implementation change (INVALIDATED/CLOSED cycles excluded from overlap check) and 3 test-payload retokening edits (scaffold-verbatim variant strings replaced with PRD-attested adjective forms).

## Step 8: Finalize PRD — 2026-07-04T15:52:24.000Z

Sanity check: line count identical (374/374, single-line edit only extended one paragraph inline). The delivery-window sentence (`A delivery whose scheduled_at falls outside...`) was preserved unchanged — impl `app.py:769-774` gates deliveries only by their parent cycle's own window and does not touch other cycles, so the new-cycle-creation narrowing doesn't affect that path.

result: PRD_FINALIZED.md at /home/ubuntu/github/CodingPRD/tasks/task_0733_office_pantry/workspace/PRD_FINALIZED.md pins §2.10's new-cycle overlap rule to `OPEN`-cycles only (terminal `CLOSED`/`INVALIDATED` cycles excluded), matching `services.py:509-530` `rotation_cycle_overlaps_existing` and unblocking pause→resume.

**Summary**

- PRD.md 374 lines, PRD_FINALIZED.md 374 lines. Text delta = one paragraph extended (+241 chars, ~0.4% by character count).
- Line-count delta: 0 lines (+0%). The edit is a single-line inline expansion.

**Change bullet**

- §2.10 (Location Capacity and Delivery Scheduling), final paragraph — revise — narrowed "any existing cycle for the same subscription" to "any existing `OPEN` cycle for the same subscription" and added a trailing sentence explicitly excluding terminal (`CLOSED`, `INVALIDATED`) cycles from new-cycle overlap gating, cross-referencing §3.3's "fresh window" rule — matches `implementation/services.py:509-530` (`rotation_cycle_overlaps_existing`, specifically line 523 which skips `("INVALIDATED", "CLOSED")`).

**Per-edit pre-edit search log**

Edit 1 — §2.10 overlap narrowing:
- (a) Subject: which rotation-cycle statuses gate a *newly-created* cycle via the overlap invariant.
- (b) Impl paths enumerated / read:
  - `services.py:509-530` (`rotation_cycle_overlaps_existing`) — skips cycles whose status is in `("INVALIDATED", "CLOSED")`; still checks OPEN cycles for the same subscription.
  - `services.py:445-448` (`invalidate_rotation_cycle`) — writes status `INVALIDATED`.
  - `app.py:716` — close sets status `CLOSED`.
  - `app.py:554` — activation callsite invoking `rotation_cycle_overlaps_existing` on the *new* first cycle.
  - `app.py:625` — resume callsite invoking `rotation_cycle_overlaps_existing` on the *new* post-pause cycle.
  - `app.py:769-774` — delivery-generation branch of `ERR_ROTATION_CYCLE_OVERLAP`; does NOT call `rotation_cycle_overlaps_existing`, only checks `eff_from <= sched_dt < eff_to` on the delivery's own parent cycle. Terminal-cycle exclusion is orthogonal here.
  - Cycle status enum per §3.4: {OPEN, CLOSED, INVALIDATED}, of which only OPEN is non-terminal.
- (c) Wording adjustment: scoped the narrowing to the specific sub-sentence about "rotation-cycle creation itself" and preserved the preceding delivery-window sentence verbatim, because the delivery branch (app.py:769-774) legitimately checks the parent cycle's window regardless of that cycle's status. Terminal-exclusion phrasing referred to §3.3 to reuse existing language rather than introduce a novel invariant.

Other Step-7 items:
- `test_suite/test_01_crud_and_lookup.py:184` and `test_suite/test_04_calculations_and_pricing.py:138,157` retokening from scaffold-leaked strings (`"authoritative_stocked_feedback"`, `"provisional_stocked_feedback"`) to the PRD-attested tokens (`"authoritative"`, `"provisional"`). PRD §3.8 already unambiguously names the variants and describes the `variant` query parameter; these are pure fixture bugs, not PRD silences. No PRD edit.

## Step 9: Complete PRD — 2026-07-04T16:03:19.000Z

Sanity check: PRD_COMPLETED.md exists and diff shows 10 revised lines, char delta +1732, line count unchanged.

result: /home/ubuntu/github/CodingPRD/tasks/task_0733_office_pantry/workspace/PRD_COMPLETED.md written with 10 minimal in-paragraph revisions pinning impl behavior.

Summary:
- Source: PRD_FINALIZED.md, 374 lines / 59506 chars
- Output: PRD_COMPLETED.md, 374 lines / 61238 chars (delta +1732 chars, 0 lines)
- Ambiguity-pins: 8; Mismatch-revisions: 2

Per-change bullets:
- §2.5 Nested Resource Retrieval — insert — ambiguity — added that a `Feedback` retrieval that does not resolve yields `ERR_FEEDBACK_NOT_FOUND`, and that an unresolved par-level id at `/par-levels/{id}` surfaces as `ERR_LOCATION_NOT_FOUND` — implementation/app.py:1146, implementation/app.py:438
- §2.7 Hierarchical Consistency — revise — mismatch — invoice fan-out on rotation-invalidate is scoped by `client_id` (all invoices under the affected client), not restricted to the origin subscription — implementation/services.py:463
- §3.1 Catalog (Plan) — insert — ambiguity — pinned that `volume_discount_threshold_headcount` is required on plan-create bodies (including FLAT plans) and must be at least 1, and that duplicate `tier` values are rejected as `ERR_INVALID_REQUEST` (HTTP 400) — implementation/app.py:112,120,126
- §3.1 Catalog (Product) — insert — ambiguity — pinned duplicate `sku` rejected as `ERR_INVALID_REQUEST` (HTTP 400) — implementation/app.py:182
- §3.1 Client-side onboarding — insert — ambiguity — pinned `service_fee_bps` defaults to 0 when omitted, and duplicate `(client_id, dietary_flag)` preference rejected as `ERR_INVALID_REQUEST` (HTTP 400) — implementation/app.py:285, implementation/app.py:347
- §3.2 Assortment (ParLevel) — insert — ambiguity — pinned duplicate `(location_id, product_id)` rejected as `ERR_INVALID_REQUEST` (HTTP 400) — implementation/app.py:391
- §3.3 Activating the subscription — insert — ambiguity — pinned that violation of the three activation preconditions surfaces as `ERR_INVALID_STATE` (HTTP 409) — implementation/app.py:540,544,548
- §3.3 Pausing — revise — mismatch — the parallel invoice-flip fan-out is scoped by `client_id`, per the §2.7 revision — implementation/services.py:463
- §3.4 Rotation Cycles and Delivery Generation — insert — ambiguity — pinned that a delivery-generator `location_id` resolving to a different client's location is rejected as `ERR_INVALID_STATE` (HTTP 409) — implementation/app.py:779
- §3.6 Disputes, Actuals, and Client Credit — insert — ambiguity — pinned that when resolve-dispute yields `dispute_credit_cents == 0`, the client hop is skipped and `client.version` is not bumped — implementation/app.py:940
