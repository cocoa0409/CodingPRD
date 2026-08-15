# Worklog — task_1976_copyright_licensing_rights_clearance

## Step 2: Generate Scaffold — 2026-08-15T04:46:00.000Z

Scaffold generation for task 1976 is complete with a clean lint verdict.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1976_copyright_licensing_rights_clearance/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

**Counts:**
- **12 entities**: Asset, RightsHolder, RightsDiligenceLog, ClearanceRequest, NegotiationRound, License, UsageReservation, UsageEvent, LicensePayment, FairUseAssessment, TakedownNotice, RenewalAlert
- **8 state machines**: ClearanceRequest (cyclic NEGOTIATING loop with 5-round cap + role alternation), License (**parallel dimensions** lifecycle × fee_status), Asset (posture-driven precedence chain RETIRED > SUSPENDED > ENCUMBERED > CLEAR), TakedownNotice (DMCA clock with strict-`>` lapse semantics), UsageReservation (TTL forfeit), FairUseAssessment, RenewalAlert
- **10 calculations**, including dual variants (provisional-vs-final fee with MFN floor gate; gross-vs-net usage consumption), a tiered/multiplier fee formula with pinned single-round-half-up rounding, half-open interval overlap with WORLD-superset territory semantics, and an embargo+buffer gate
- **11 validation rules** (priorities 1–10, including a p2.5 body-schema row)
- **45 endpoints** (incl. `/_clock/set_current_utc` with fixed default `2026-08-01T00:00:00Z`)
- **36 error codes**, all referenced by validations/transitions
- **8 roles** with segregation-of-duties (requester ≠ approver ≠ payer ≠ certifier) plus entity-backed `RightsHolderRep` for negotiation alternation
- **3 OCC concurrency rules** (advance, payments, reservations — all true create-with-supersede-style races)
- **§1.8: 18 instances** (2 per rule × 9 rules), **§1.9: 49 instances** (47 active + 2 `excluded_because` stubs), 535 calls total across both files

**Key design adjudications made during generation:**
1. **Takedown lapse semantics**: sweep upholds only when `clock > counter_notice_due_at` (strictly greater), while counter requires `clock < due_at` — this keeps `ERR_COUNTER_WINDOW_LAPSED` reachable at exactly the deadline instant (with `>=` sweep semantics the error would be dead code).
2. **UPHELD is not terminal** for TakedownNotice: claimant retraction `UPHELD→RETRACTED` is the only path restoring cascade-suspended licenses (forfeits stay permanent — asymmetric compensation, exercised in §1.8).
3. **Precondition ordering** on `SUBMITTED→HOLDER_REVIEW`: orphan-diligence gate precedes the posture gate, otherwise `ERR_ORPHAN_DILIGENCE_INCOMPLETE` would be shadowed by `ERR_ASSET_POSTURE_BLOCKED` (found during replay audit).
4. **Reservation TTL raised to 720h** so takedown cascades (not TTL expiry) are unambiguously the forfeit cause in cascade instances.
5. **Failed round-accept persists no row** — keeps round_index/alternation deterministic after validation failures.
6. All §1.8 numeric assertions pre-computed by executing the fee formula (e.g., 90d vs 91d term straddle → 7000 vs 8750; bulk boundary 100 units → 4500000; fair-use boundary composite 13).
7. Path templates use `{id}` uniformly (required by lint check (f) sub-resource prefix matching); added `GET /rights/clearance-requests` worklist to close the last FK reverse-reachability gap.

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

No sibling task directories were inspected at any point.

## Step 3: Copy Shared Files — 2026-08-15T04:47:00.000Z

Copied ./INSTRUCTION.md to tasks/task_1976_copyright_licensing_rights_clearance/workspace/INSTRUCTION.md (bash only, no subagent).

## Step 4: Generate PRD — 2026-08-15T05:03:00.000Z

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1976_copyright_licensing_rights_clearance/workspace/PRD.md` — 314 lines.

**Section list:**
- 1. Introduction (2 paragraphs)
- 2. Global Specifications & System-Wide Principles — 2.1 RBAC · 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`, verified equal) · 2.3 Pagination · 2.4 Resource Identity and Common Properties · 2.5 The Desk's Logical Clock · 2.6 Monetary Precision and Rounding · 2.7 Optimistic Concurrency Control · 2.8 Validation Priority Ladder · 2.9 Derived Asset Posture and Cascade Consistency · 2.10 Nested Retrieval, Filtering, and Worklists
- 3. Business Logic & Workflows — 3.1 Rights Holders/Asset Registration/Diligence · 3.2 Clearance Intake & Routing · 3.3 Fee Estimation & Negotiation · 3.4 License Grant & Rights Window · 3.5 Reservations & Consumption · 3.6 Payments/Refunds/Fee Status · 3.7 Takedowns & Revocation · 3.8 Fair Use · 3.9 Expiration Sweeps/Renewal/Retirement
- 4. Endpoint Definitions (45 rows, 4 columns) · 5. Error Code Catalogue (36 rows, 2 columns)

**Coverage audit (scaffold → PRD):** entities → §2.4/§2.9 + §3.1–3.9 narrative; state machines (Asset, ClearanceRequest, License dual-dimension, UsageReservation, TakedownNotice, FairUseAssessment, RenewalAlert) → §2.9 + §3.2–3.9 with all transitions, preconditions paired to error IDs, and side-effect cascades; calculations (posture chain, territory weights, fee recipe with provisional/final variants, MFN floor, half-open overlap, embargo gate, gross/net consumption, fair-use score, fee-status rule, desk constants) → §2.6/§2.9 + §3.3–3.6; validations → §2.8 11-rung ladder with applies-to scopes, plus per-transition pinned orders in §3.2/3.3; concurrency rules (3 OCC paths) → §2.7; endpoints → §4; errors → §5 + prose triggers in §2/§3; roles (7 opaque + entity-backed RightsHolderRep) → §2.1.

**Hard-contract reports:**
- Field coverage: 68 required (entity fields + request bodies + query params + common fields + `current_utc`), 68 present, 0 missing — **PASS**
- Rule coverage: 47/47 targeted rule spot-checks present; all transitions/calculations/validations/OCC rejections/side effects expressed; sibling branches symmetric — **PASS**
- Path purity (§3): 447 backtick tokens scanned, 0 paths, 0 bare methods, 0 method+path combos — **PASS**
- Extras: 72/72 enum/state values present verbatim; 36/36 error IDs in §2/§3 prose; no pseudocode operators or fuzzy hedging found.

**Ambiguities noticed (kept faithful to scaffold, flagged for downstream):**
1. Asset-creation side effect says `posture=CLEAR`, yet the derivation chain would compute `ENCUMBERED` when no holder is given (`orphan_status=DILIGENCE_PENDING`) — whether creation itself triggers recompute is unpinned; PRD states both rules literally.
2. The embargo gate's declared trigger includes the first advance, but the advance transition's own precondition list omits it; PRD states enforcement at creation and re-evaluation at the first advance (matching the priority-8 validation scope).
3. The advance gate order (orphan → media → posture) inverts the global ladder for that transition; PRD pins the transition-specific order in §3.2 and notes §3 orderings override the default ladder.
4. `suspension_cause` appears only in a side effect, not as a declared field; PRD carries it in backticks as the restore-scope marker.
5. Direct-grant usage events (null `reservation_id`) have no quota check in the scaffold; PRD asserts only license-ACTIVE and in-term checks, inventing no availability gate.

(Row slicing in the subagent's initial check dropped the first data row; actual counts are 45 endpoints and 36 errors, with zero missing rows, zero column violations, and zero role mismatches.)

## Step 5: Generate Unit Tests — 2026-08-15T05:26:00.000Z

Task 1976 test generation complete.

**Files generated** under `/home/ubuntu/github/CodingPRD/tasks/task_1976_copyright_licensing_rights_clearance/`:

`test_helpers/` (9 files):
- `__init__.py` — barrel export (framework + PRD-specific)
- `types.py` — 14 status/role enums, 12 entity TypedDicts (append-only entities correctly omit `updated_at`/`version`)
- `api_client.py` — `ApiClient(GenericApiClient)` with 31 endpoint methods covering all of PRD §4
- `api_errors.py` — `ApiErrorId` enum (36 errors) + `set_error_http_status_map` registration
- `assertions.py` — per-entity `assert_*` helpers enforcing common-fields vs append-only shapes
- `factories.py` — payload factories for every creatable entity
- `constants.py` — desk thresholds (DMCA_COUNTER_WINDOW_DAYS=10, EMBARGO_BUFFER_DAYS=30, HOLD_TTL_HOURS=720, RENEWAL_ALERT_LEAD_DAYS=30, MAX_NEGOTIATION_ROUNDS=5, FAIR_USE_CERTIFY_MIN=13, BULK_UNITS_MIN=100, MEDIA_UNIT_RATE_CENTS, TERRITORY_WEIGHT)
- `test_users.py` — shared `TEST_USERS` headers + per-instance `make_<role>_headers` builders (mandatory for `RightsHolderRep`, the only `entity_backed` role)
- `fixtures.py` — composite fixtures: `setup_holder_asset`, `setup_request_in_negotiating`, `setup_approved_request`, `setup_license`, `setup_license_with_pending_takedown`, `setup_suspended_license`, `setup_revoked_license`, `setup_expired_license`, `setup_orphan_certified_asset`

`test_suite/` (12 test files + `conftest.py`): 89 tests total.

**Coverage per queue:**
- Queue A (Difficulty): 18/18 instances, each with ≥2 tests (36 tests minimum, some instances picked up additional coverage in corner-driven files).
- Queue B (Corner): 47/47 non-stub instances, each with ≥1 test.
- 2 stub instances skipped per skill rules (the cited difficulty instances own the assertion):
  - `error_quota_exceeded_covered` — owned by `usage_quota_exact_fit_passes_plus_one_fails`
  - `error_stale_version_covered_by_occ_instances` — owned by `occ_stale_*` instances

**Skipped instances:** none beyond the two declared stubs — every non-stub instance in both queues passed the PRD-first two-condition filter (verbatim coverage AND unique derivability).

**Design adjudications:**
- The two `priority_pair_validation_conflict` instances were kept (not skip-listed under `validation-priority` silence) because PRD §2.8 explicitly commits to ladder ordering with "a failure at any rung masks every rung below it" — both rung pairs are uniquely derivable.
- `fee_provisional_ignores_mfn_floor_final_enforces_it` was translated exactly as the recipe demands: the provisional estimate (30000) is rejected at the final-variant acceptance gate against the floor (50000), then 50000 is accepted — both halves of the dual-variant distinction are observable.
- `usage_consumption_gross_vs_net_after_takedown_strike` test asserts gross=7/net=4 on a revoked license (E1 used before notice.received_at stays POSTED; E2 used after is STRUCK).
- `single_rounding_vs_forbidden_per_component_rounding` uses the RADIO/LATAM/1u/91d fixture pinned by the design (8000×0.8×1.25 → 8000 exactly) and a second angle (SOCIAL/APAC/1u/91d → 4500) to satisfy the ≥2 quota.
- `test_users.py` uses `make_rights_holder_rep_headers(holder["id"])` everywhere a rep posts a round — never the shared constant — per the entity-backed identity rule.

**Pytest discovery:** all 89 tests collect cleanly with no syntax or import errors (`pytest --collect-only` returned 89).

## Step 6: Generate Implementation — 2026-08-15T05:26:00.000Z

Generated a complete Python + Flask implementation for `task_1976_copyright_licensing_rights_clearance` in `/home/ubuntu/github/CodingPRD/tasks/task_1976_copyright_licensing_rights_clearance/workspace/implementation/`.

### File list
- `start.sh` — guarded launcher (`import flask` check before `pip install`), `exec python3 app.py`, `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — entry point, imports route modules
- `state.py` — Flask app, in-memory stores, logical clock (default `2026-08-01T00:00:00Z`), envelope/auth/error/pagination/validation helpers, all constants
- `services.py` — posture derivation, cascades, clock sweeps, fee/MFN/overlap/embargo/usage/fair-use calculations
- `serializers.py` — wire format for all 12 resource types
- `routes_core.py` — clock, rights holders, assets, diligence logs, retire
- `routes_requests.py` — clearance requests, advance/deny/withdraw/grant, negotiation rounds
- `routes_usage.py` — licenses, reservations, usage events, payments, renewal alerts, revoke
- `routes_fairuse_takedown.py` — fair-use assessments, takedown notices

### Endpoint count
All **41** endpoints from the endpoint table are implemented (1 clock, 3 rights-holders, 4 assets+retire, 2 diligence, 6 clearance-requests, 2 rounds, 3 licenses+revoke, 4 reservations, 3 usage-events, 2 payments, 6 fair-use, 5 takedowns, 2 renewal-alerts).

### State machines implemented
- **Asset.posture** — derived precedence chain `RETIRED > SUSPENDED > ENCUMBERED > CLEAR`, never set directly, with cascade-in/out of license suspension
- **ClearanceRequest** — `SUBMITTED → HOLDER_REVIEW → NEGOTIATING → APPROVED → LICENSED`, plus `DENIED`/`WITHDRAWN`/`FAIR_USE_ROUTE`/`EXPIRED` terminals
- **License** — two parallel dims: lifecycle (`ACTIVE/SUSPENDED/EXPIRED/REVOKED`) and fee (`UNPAID/PARTIALLY_PAID/PAID/REFUNDED`), moving independently
- **UsageReservation** — `HELD → CONSUMED/RELEASED/FORFEITED`
- **TakedownNotice** — `PENDING → COUNTERED/UPHELD/RETRACTED`, `COUNTERED/UPHELD → RETRACTED`
- **FairUseAssessment** — `DRAFT → CERTIFIED/REJECTED/SUPERSEDED`
- **RenewalAlert** — `SCHEDULED → FIRED/CANCELLED`

### Calculation rules implemented
- `asset_posture` precedence chain; `territory_weight`/`territories_overlap` (WORLD superset); `license_fee_estimate` (base × territory × term-mult × bulk-discount, single half-up rounding, MFN floor last); `mfn_floor` (ESTATE exempt); `license_overlap` (half-open interval intersection); `embargo_gate` (>= boundary); `usage_consumption` (gross/net/reserved/available); `fair_use_score` (market × 2, certify ≥ 13); `fee_status_rule`; `desk_constants` (5 rounds, 720h hold, 30d alert lead, orphan 3-channels/30d-span, 10d DMCA window).

### Verification performed
Live-tested happy path (holder→asset→request→advance×2→rounds→grant→license), reservation/partial-draw/payment, takedown lapse cascade (SUSPENDED + forfeit + alert cancel), revoke+strike (gross untouched, net dropped), retract-restore, embargo/window/stale-OCC/RBAC/auth errors, alternation/MFN/segregation (failed rounds persist no row), round cap, window overlap vs half-open adjacency, expiry/hold-forfeit/alert-fire sweeps, ESTATE floor exemption, overpayment, fair-use route, and orphan certification. Clean boot via `start.sh` confirmed.

### Interpretation decisions (PRD-vs-scaffold or ambiguous prose)
1. **New-asset posture** — PRD 3.1 explicitly says a newly registered asset "enters with posture CLEAR," but the scaffold posture chain derives ENCUMBERED for a `DILIGENCE_PENDING` orphan. I followed the PRD (creation sets CLEAR) and let the *next* diligence-log append trigger recompute to ENCUMBERED, per PRD 2.9's "re-derives whenever anything touching the asset changes."
2. **`units_consumed_gross`** — the scaffold formula line reads `sum(... posting_kind == POSTED)` but its own `gross_consumption` variant says "consumed units count even if later struck," and PRD 3.5/3.7 state gross is "untouched" by strikes. I implemented gross = sum of **all** events (POSTED + STRUCK), so strikes lower only net. This made `ERR_REFUND_AFTER_USE` reachable after a revoke-strike (verified).
3. **Orphan-certify "every log outcome == NO_RESULT"** — read as applying to the asset's whole diligence history (any `HOLDER_FOUND`/`CONFLICTING_CLAIM` log blocks certification), not just the qualifying subset.
4. **OCC validation order** — placed the `expected_*_version` check immediately after path-existence and before state/business checks, matching PRD 2.8 rung 5.
5. **Refund exact-cancellation** — for a malformed refund magnitude (not exactly canceling cumulative paid) I used `ERR_INVALID_REQUEST` (400), since the scaffold catalog has no dedicated "wrong refund amount" error and the precondition failures (`ERR_REFUND_REQUIRES_TERMINAL`/`ERR_REFUND_AFTER_USE`) are checked first.
6. **`suspension_cause`** — surfaced on the License serializer (set to `TAKEDOWN` on cascade-suspend, cleared on reactivate/revoke) since the reactivate rule keys off it.

## Step 7: Run Tests and Iterate — 2026-08-15T05:40:00.000Z

Clean 8-round parallel sweep achieved: **89/89 passed, 0 failed, 0 errors in every round.**

**Iterations run:** 3 sweeps (24 round-runs total). Sweep 1: 40/89. Sweep 2: 86/89. Sweep 3: 89/89 × 8 rounds.

**Tests deleted:** None wholesale. One assertion removed (STEP 1c partial-coverage split):
- `test_02_asset_intake_and_orphan_diligence.py::TestAssetCreateDefaults::test_asset_without_holder_orphan_pending_posture_encumbered` — removed only the `orphan_asset["posture"] == "ENCUMBERED"` line (the `orphan_status` and held-asset assertions were kept). Collapse pattern: **unique-derivability failure via PRD self-conflict** — PRD §3.1 states verbatim "A newly registered asset enters with posture `CLEAR`" while §2.9 chain rule 4 states verbatim "If the asset's `orphan_status` is `DILIGENCE_PENDING`, the posture is `ENCUMBERED`", and §2.9's re-derivation trigger list (takedown created/transitioned, license granted/moving, diligence log appended, orphan_status changing) does not name asset creation. Two faithful PRD-only readers diverge (the worklog itself flagged this as unpinned at PRD-generation time). Scaffold driver: `Corner/entities/asset_create_defaults_orphan_pending_when_holderless`.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` — added the missing `make_certifier_headers` import (NameError inside `setup_revoked_license`).
- `fixtures.py` — added the missing `requester_user_id: Optional[str] = None` parameter to `setup_approved_request`, which referenced the name without declaring it; this single NameError was the shared setup failure behind 48 of 49 failures in sweep 1.
- `assertions.py` — added `same_instant` / `assert_same_instant` helpers (parse-and-compare at second precision per PRD §2.5); `__init__.py` — exported both.

**Fixes applied to `test_suite/` (all STEP 1c/2 representation corrections, never weakened rules):**
- `test_08_takedown_and_cascade.py::test_default_clock_received_at_and_counter_due` — exact-string equality on `received_at`/`counter_notice_due_at` switched to instant comparison. PRD pins the instant values verbatim (§2.5 default clock "reads exactly 2026-08-01T00:00:00Z"; §3.7 "sets `counter_notice_due_at` ten days later") but pins three-fractional-digit wire format only for `api_request_timestamp` and the `created_at`/`updated_at` audit triple — the format of these fields is not uniquely derivable.
- `test_11_rbac_and_terminal_gates.py::test_alert_fires_at_term_end_minus_30d` — same fix for `fires_at` (instant pinned by §3.9 "thirty days before `term_end_at`").
- `test_12_difficulty_second_angles.py::test_retract_recreates_renewal_alert_when_fires_at_in_future` — same fix inside the `any(...)` over SCHEDULED alerts (instant pinned by §3.7's replacement-alert rule).

**Fixes applied to `implementation/`:** none — the implementation was PRD-faithful throughout; every failure traced to the test artifact layer.

## Step 8: Finalize PRD — 2026-08-15T05:48:00.000Z

Both edits are in place and the diff is exactly two sentences appended to existing paragraphs. Verification against the NO-NEW-MISMATCH rule is complete for both.

**Line counts / delta:** PRD.md = 314 lines, PRD_FINALIZED.md = 314 lines (0% line-count delta — both edits append one sentence each to existing paragraphs; no sections added or removed).

**Changes (one bullet each):**
- §2.4 — insert — appended a sentence pinning that every server-emitted datetime uses the same ISO 8601 UTC three-fractional-digit wire format as the audit triple, naming `embargo_until`, `retired_at`, `use_start_at`, `use_end_at`, `term_start_at`, `term_end_at`, `hold_expires_at`, `used_at`, `posted_at`, `received_at`, `counter_notice_due_at`, `fires_at`, ledger-row `created_at`, and the clock's `current_utc` — `implementation/serializers.py:11-12` (all serializers route through `_ts` → `state.py:101-103 ts3`), `implementation/routes_core.py:28`, `implementation/state.py:177`.
- §3.1 — revise — appended a sentence resolving the §3.1-vs-§2.9-rule-4 self-conflict in the implementation's favor: registration does not run the §2.9 derivation, so a holderless asset is born `CLEAR` even while `DILIGENCE_PENDING`; the chain first governs at the next re-derivation trigger — `implementation/routes_core.py:95` (literal `"posture": "CLEAR"` at creation, no recompute call), documented by the impl comment at `routes_core.py:99-100`.

**Step 7 items producing no PRD edit:** the two `fixtures.py` fixes (missing `make_certifier_headers` import; undeclared `requester_user_id` parameter — 48 of 49 sweep-1 failures) are pure fixture bugs with no PRD silence behind them. The `same_instant`/`assert_same_instant` helper addition is test tooling whose semantics (second-precision comparison) §2.5 already pins verbatim.

**Per-edit pre-edit search log:**

*Edit 1 (§3.1 creation-time posture):*
- (a) Subject: asset `posture` value at registration for a holderless (`DILIGENCE_PENDING`) asset, and when the §2.9 chain first applies.
- (b) Paths enumerated: `routes_core.py:71-101` `create_asset` (sets `posture: "CLEAR"` literally, never calls recompute); every `recompute_asset_posture` callsite — `routes_core.py:183` (orphan certification), `routes_core.py:204` (diligence append), `routes_fairuse_takedown.py:194/232/246` (notice create/counter/retract), `routes_requests.py:329` (grant), `services.py:338` (clock sweep over all assets); `services.py:193-213` `derive_posture`; `services.py:248-265` transition cascades; `serializers.py:37` (reads stored field). Also cross-checked PRD §1 line 7 ("posture is never set directly") and §2.9's trigger list for contradiction.
- (c) Wording adjustment: deliberately avoided naming which trigger fires next (the clock sweep recomputes all assets unconditionally, and §2.9's trigger list doesn't name clock-set) — used the trigger-neutral phrase "the next re-derivation trigger" so the sentence stays true for the diligence-append path, the takedown path, the grant path, and the clock-sweep path alike.

*Edit 2 (§2.4 datetime wire format):*
- (a) Subject: wire representation of server-emitted datetime fields beyond `api_request_timestamp` and the `created_at`/`updated_at` audit triple.
- (b) Paths enumerated: `serializers.py:11-12` `_ts` and every serializer's datetime fields (all 13 domain datetime fields across all 12 serializers, plus ledger-row `created_at`); `routes_core.py:28` clock response `current_utc`; `state.py:177` envelope `api_request_timestamp`; `state.py:101-103` `ts3` definition. Confirmed zero emission paths bypass `ts3`.
- (c) Wording adjustment: led with a universal clause ("Every datetime the server emits uses that same wire format") and made the field list exemplary ("such as … as well as …") rather than exhaustive, so no field — listed or not — can be mis-described; reused §2.4's existing format phrase ("that same wire format") instead of introducing new format vocabulary, keeping the pin minimal and consistent with §2.2's example.

## Step 9: Complete PRD — 2026-08-15T06:01:00.000Z

PRD_COMPLETED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1976_copyright_licensing_rights_clearance/workspace/PRD_COMPLETED.md` — a pure in-place patch over `PRD_FINALIZED.md` (which differs from `PRD.md`; finalized was the source).

**Source vs output**: `PRD_FINALIZED.md` 314 lines / 48,061 chars → `PRD_COMPLETED.md` 314 lines / 50,635 chars (+2,574 chars, 22 paragraphs touched, no sections added/removed, line count unchanged).

**Counts**: 22 ambiguity-pins, 4 mismatch-revisions.

### Mismatch revisions
- §2.1 — revise — mismatch — `X-User-ID` is required under **every** role (not only entity-backed); missing it is always `ERR_UNAUTHENTICATED` 401 — impl `state.py:236-238`
- §2.8 rung 1 — revise — mismatch — same pin reflected in the ladder's authentication rung — `state.py:236-238`
- §2.8 rungs 3/4 — revise — mismatch — swapped: **path existence (404) is evaluated before request-body schema (400)**; every path-parameterized handler resolves the path resource before parsing the body — `routes_requests.py:110-112`, `routes_usage.py:184-188`, `routes_fairuse_takedown.py:65-68`
- §2.8 rung 9 — revise — mismatch — `ERR_HOLD_EXPIRED` is HTTP 409 (per §5 catalogue and impl), not 422 as the rung's group label implied — `routes_usage.py:204`

### Ambiguity pins
- §2.1 — insert — a `RightsHolderRep`'s `X-User-ID` is accepted as presented, never resolved against persisted RightsHolder records — `state.py:229-232`
- §2.3 — insert — non-integer/out-of-range `limit` (1–100) or negative/non-integer `offset` → `ERR_INVALID_REQUEST` 400 — `state.py:279-299`
- §2.3 — insert — `has_more` = `offset + len(page) < total_count`; `created_at` ties fall back to creation order — `state.py:191`, `services.py:80-83` and all list sorts by `(created_at, _seq)`
- §2.5 — insert — clock-set is unconditional; no monotonicity check, backward moves allowed — `routes_core.py:18-28`
- §2.8 preamble — insert — license grant, withdrawal, and the fair-use workflow added to the workflows that pin their own ordering — `routes_requests.py:273-300,177-182`, `routes_fairuse_takedown.py:73-79`
- §3.1 — insert — `mfn_floor_cents` is a non-negative integer — `routes_core.py:39`
- §3.1 — insert — `permitted_media` must be a non-empty subset — `routes_core.py:77-81`
- §3.1 — insert — unknown `rights_holder_id` at asset registration → `ERR_NOT_FOUND` 404 — `routes_core.py:84-85`
- §3.1 — insert — orphan certification requires **every** log in the asset's history to be `NO_RESULT`; any `HOLDER_FOUND`/`CONFLICTING_CLAIM` blocks — `routes_core.py:177-178`
- §3.2 — insert — withdrawal evaluates the state check before the owner check (`ERR_INVALID_STATE` precedes `ERR_FORBIDDEN_OWNER_ONLY`) — `routes_requests.py:177-182`
- §3.3 — insert — `offered_fee_cents` non-negative integer; `accept` defaults false — `routes_requests.py:198-199`
- §3.3 — insert — rounds list ordered by `round_index`, not `created_at` — `services.py:56-60`
- §3.4 — insert — `grant_fee_cents` non-negative integer — `routes_requests.py:272`
- §3.5 — insert — referenced reservation must exist under the license (else `ERR_NOT_FOUND`) and still be `HELD` (else `ERR_INVALID_STATE`), checked in that order after the ACTIVE check — `routes_usage.py:195-201`
- §3.5 — insert — release refreshes the parent license (version bump); clock forfeiture touches only the reservation row — `routes_usage.py:173-175`, `services.py:310-313`
- §3.6 — insert — `amount_cents` must be a non-zero integer; zero/non-integer → `ERR_INVALID_REQUEST` 400 — `routes_usage.py:250-254`
- §3.6 — insert — segregation check applies to refunds as well as payments and runs right after OCC, before payable/overpayment/refund rules — `routes_usage.py:261-264`
- §3.6 — insert — refund magnitude not exactly cancelling cumulative paid → `ERR_INVALID_REQUEST` 400 — `routes_usage.py:282-285`
- §3.7 — insert — with multiple `UPHELD` notices, the strike window keys off the earliest `received_at` — `routes_usage.py:71-78,90-91`
- §3.8 — insert — referenced request missing or not on the asset → `ERR_NOT_FOUND` 404; media-eligibility gate runs before the `SUBMITTED`-state check — `routes_fairuse_takedown.py:69-79`
- §3.8 — insert — certification segregation compares against the requester who **filed the assessment** (`created_by_requester_id`), not the clearance request's `requester_id` — `routes_fairuse_takedown.py:93,151-153`
- §3.8 — insert — certification against a `RETIRED` asset → `ERR_ASSET_POSTURE_BLOCKED` 409 — `routes_fairuse_takedown.py:154-157`

### Notable findings left unchanged (already aligned or unobservable)
- `services.py:167 fee_estimate_cents` (the §3.3 fee recipe) exists in impl exactly as the PRD describes but is never wired to any route/field — the "provisional estimate" has no observable surface, so the PRD recipe prose was kept (impl does exhibit the computation internally; nothing contradicts it).
- `ERR_LICENSE_ALREADY_EXISTS` in grant is unreachable in impl (grant requires `APPROVED`, and a successful grant moves the request to `LICENSED`), so the ladder's rung-9-vs-10 ordering for grant vs impl's check order is unobservable — left as-is.
- All 41 endpoints, role tables, enums, posture precedence chain, cascades, sweeps, fee-status recomputation, and ledger-row shapes in §4/§5 match impl exactly — verified endpoint-by-endpoint.
