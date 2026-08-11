# Worklog — task_0967_breast_pump_maternity_dme

## Step 1: Create Task Directory — 2026-08-10T02:18:55.959Z

Pre-assigned output folder `tasks/task_0967_breast_pump_maternity_dme` with `workspace/` subdirectory already existed; Step 1 treated as done per headless-run instructions (no auto-index scan run).

## Step 2: Generate Scaffold — 2026-08-10T02:54:33.144Z

All three scaffold artifacts are generated, lint-clean, and verified on disk.

**Files**
- `/home/ubuntu/github/CodingPRD/tasks/task_0967_breast_pump_maternity_dme/SCAFFOLD.yaml` (§1.0–§1.7 only)
- `/home/ubuntu/github/CodingPRD/tasks/task_0967_breast_pump_maternity_dme/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_0967_breast_pump_maternity_dme/SCAFFOLD_CORNER_DESIGN.yaml` (single top-level key `scaffold_corner_design`)

**Counts**
- Entities: 12 (Member, InsurancePolicy, Prescription, CatalogItem, PumpOrder, OrderLine, PriorAuthorization, Shipment, Claim, ResupplySchedule, ResupplyOrder, WarrantyClaim)
- Endpoints: 55 (incl. `/dme/_clock/set_current_utc` with fixed default 2026-05-01T00:00:00Z)
- State machines: 10 (parallel fulfillment × billing dimensions on PumpOrder; cyclic machines on Prescription, PriorAuthorization, Claim, WarrantyClaim)
- Calculations: 7 (incl. dual-variant provisional-vs-adjudicated billing, ROLLING vs CALENDAR_ANCHORED resupply cadence, pinned per-line rounding, circular-looking bundle-discount ordering, nested-min/max adjudication waterfall)
- Validations: 26 priority-ordered rules; Error codes: 38; Roles: 6 (segregation-of-duties: claim submitter ≠ remittance poster); Concurrency rules: 2 (OCC on PumpOrder.version and ResupplySchedule.version)
- Difficulty (§1.8): 9 rules × ≥2 instances = 20 instances, all with structured `setup_api_calls`/`trigger` chains and precomputed literal asserts (e.g., provisional 30000 vs adjudicated 25000; ROLLING 2026-11-08 vs CALENDAR_ANCHORED 2026-10-28; per-line discount 1000 vs sum-then-round 999)
- Corner (§1.9): 61 entries (47 active test instances + 14 `excluded_because` stubs) across entities / state_machines / calculations / validations / endpoints / errors / rbac / cross_cutting_layers / consistency_model

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (55 endpoints, 12 entities, 20 §1.8 + 47 §1.9 active instances, 627 calls scanned; one FK-reverse-reachability violation found and fixed by adding `replacement_shipment_id?` to `GET /dme/warranty-claims`.)

Key design choices for the beyond-expert target: lazy (not clock-eager) expiry transitions so `ERR_PRESCRIPTION_EXPIRED`/`ERR_PRIOR_AUTH_EXPIRED`/`ERR_BENEFIT_PERIOD_ENDED` stay reachable and state-vs-temporal priority ordering is testable; density over volume — 12 entities with deep coupling (delivery cascade depth 3, warranty-replacement cascade with posture lock, compensating qualify/cancel and remit/void invariants). No sibling task directories were inspected.

## Step 3: Copy Shared Files — 2026-08-10T02:54:51.737Z

Copied `./INSTRUCTION.md` → `tasks/task_0967_breast_pump_maternity_dme/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-10T03:00:19.868Z

PRD generated and verified on disk.

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_0967_breast_pump_maternity_dme/workspace/PRD.md` — 328 lines, ~52 KB.

**Section coverage**:
- §1 Introduction (3 paragraphs, business-context angle)
- §2 Global Specifications (10 subsections: RBAC with per-role identity translation, verbatim §2.2 response envelope, pagination with limit default 10/min 1/max 100 and `created_at` ascending sort, common properties + both OCC rules, logical clock with 2026-05-01T00:00:00Z startup default and lazy-expiry semantics, pinned rounding/evaluation orders, benefit-window/allowance/prior-auth-threshold gates, the full 10-priority validation pipeline, polymorphic FK rules for Shipment/Claim, and cascade/compensation principles)
- §3 Business Logic (8 subsections organized by lifecycle: onboarding → order composition → qualification/PA → shipment/delivery → resupply cadence (ROLLING vs CALENDAR_ANCHORED) → claims/adjudication waterfall → warranty → cancellations/termination), with all formulas in precise prose (round-half-up per line then sum, $200.00 bundle threshold at 10%, inclusive prior-auth threshold, deductible/coinsurance/OOP-cap waterfall with the remittance-balance invariant, strictly-greater calendar-anchor snapping vs inclusive eligibility test)
- §4 Endpoint table: 55 endpoints, 4 columns only (Method, Path, Description, Authorized Roles)
- §5 Error catalogue: all 41 error IDs, 2 columns only

**Hard contract reports**:
- Contract 1 (Field-Name Coverage): 106 required identifiers (entity fields + request/query/path params), 106 present, 0 missing — PASS
- Contract 2 (Rule Coverage): 10 validation priority groups expressed in order; 2/2 OCC rules with endpoint + `expected_*_version` + `ERR_STALE_VERSION`/412; all state-machine transitions (10 machines incl. parallel `billing_status` dimension) with preconditions and side effects; 7/7 calculations fully expressed; all validations matchable to error IDs in §2/§3 prose; all endpoint side effects and cross-entity cascades (delivery → schedules → member aggregates, cancel compensation, void reversal, policy-terminate sweep, warranty-replacement budget at 2) covered; sibling branches (shipment advance, payer decisions, warranty decisions, delivery cascade cases) at equal density — PASS
- Contract 3 (§3 Path Purity): 505 backtick tokens scanned in §3, 0 path tokens, 0 bare HTTP methods, 0 method+path combos — PASS

The withheld difficulty/corner design files were not read.

## Step 5: Generate Unit Tests — 2026-08-10T03:22:35.895Z

Done. All deliverables are on disk and all self-checks pass.

**Queue A (Difficulty): 20/20 instances translated, 0 skipped.** Each got ≥2 tests (40+ tests). All passed the PRD-first filter — the PRD covers every asserted rule verbatim (pipeline priority §2.8, both cadence variants §3.5, the waterfall §3.6, inclusive thresholds §2.7, cascades §3.4/§3.7, compensation §3.8).

**Queue B (Corner): 47/47 non-stub instances translated, 0 instances skipped; 14 `excluded_because` stubs correctly not translated** (2 calculations, 8 errors, 4 cross-cutting) — all stub `difficulty_instance` pointers verified to resolve.

Partial-assertion adjudications (instance translated, PRD-silent sub-assertions dropped rather than weakening the test):
- `catalog_item_defaults_applied` — asserts only `insurance_tier == STANDARD` (PRD §3.2 "(the default)"); other field defaults are PRD-silent (default-value silence pattern).
- `order_computed_fields_input_ignored` — pre-qualify `provisional_patient_cents == 0` is not uniquely derivable; asserted instead that the injected `999999` is not honored, plus the PRD-covered pricing totals and birth states.
- `pump_order_list_filter_and_pagination` — pump-order list filters are never named in PRD prose; test covers the §2.3 pagination contract only.
- `state_beats_temporal_on_qualify_cancelled_order` — the post-rejection prescription status is ambiguous under the two-reader test (lazy-expiry touch vs. pipeline short-circuit); asserted only the winning error and the unchanged CANCELLED order.

**Files generated:**
- `test_helpers/` — `types.py` (12 entity TypedDicts, all status/role enums), `api_client.py` (45 endpoint methods), `api_errors.py` (39 errors registered with the framework), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (per-instance builders incl. entity-backed Member and SoD-sensitive billing/insurance ids), `fixtures.py` (tiered composites: pending/verified/qualified/delivered orders, delivered-with-schedule, delivered-with-claim, qualified-with-PA, clock control), `__init__.py` barrel.
- `test_suite/` — `conftest.py` + 12 test files (member onboarding, policy lifecycle, prescriptions, catalog/order composition + bundle pricing, qualification, prior auth, shipment/delivery cascade, claims/remittance, resupply, warranty, order PATCH/OCC, cancel compensation).

**Self-check results:** 98 test functions, 98 Design tags, 0 dangling/dual tags; 20/20 difficulty instances at ≥2 tests; 47/47 corner non-stub at ≥1; 120/120 docstring PRD quotes grep verbatim against PRD.md; all files byte-compile; `test_helpers` + `conftest` import cleanly; no `skip`/`skipif`/`xfail` markers; no scaffold references in generated code.

## Step 6: Generate Implementation — 2026-08-10T03:22:35.895Z

Implementation complete and boot-verified.

**Files** in `/home/ubuntu/github/CodingPRD/tasks/task_0967_breast_pump_maternity_dme/workspace/implementation/`:
- `start.sh` — executable launcher; guards `pip install` behind `python3 -c "import flask"`, then `exec python3 app.py` (foreground, `0.0.0.0:$PORT`, default 10000)
- `requirements.txt` — flask
- `app.py` — app factory, blueprint registration, `ApiError`/404/405/500 handlers emitting the PRD §2.2 error envelope
- `db.py` — in-memory `Store` (dicts keyed by id, empty on every boot), logical clock pinned to `2026-05-01T00:00:00Z` at startup, millisecond ISO-8601 timestamp helpers
- `errors.py` — `ApiError(error_id, message, http_status)`
- `response.py` — success/error envelopes (`meta.api_request_id` `req_…`, `response_type`, `data`; pagination fields in meta for lists)
- `middleware.py` — auth pipeline (401/403/ownership 403), shape validators, `limit`/`offset` pagination (default 10, min 1, max 100), query filters, Member list scoping
- `services.py` — pinned calculations (per-line round-half-up pricing, bundle discount on pre-discount subtotal ≥ 20000, ROLLING/CALENDAR_ANCHORED cadence, adjudication waterfall with OOP cap, month arithmetic), member aggregate recompute, version/timestamp bumping
- `routes_core.py` — members, policies (+terminate cascade), prescriptions (lazy expiry on verify/resubmit), catalog, `POST /dme/_clock/set_current_utc`
- `routes_ops.py` — pump orders (create/PATCH with OCC, qualify, cancel compensation, garment lines with projective allowance check)
- `routes_ops2.py` — prior authorizations (submit/decide/resubmit/appeal, lazy PA expiry at shipment), shipments (PA gate, delivery cascade creating schedules), claims (polymorphic, SoD, waterfall remit, appeal, void reversal)
- `routes_supply.py` — resupply schedules (PATCH with OCC, suspend/resume), resupply orders (window/quantity/benefit-period gates, cancel rollback), warranty claims (decide/reopen≤2/resolve with replacement-shipment cascade and budget of 2)

**Endpoint count:** 55 routes under `/dme` — exactly the PRD §4 table (no extra endpoints added; verified via `url_map` dump).

**Boot verification:** `PORT=18124 bash start.sh` booted cleanly from a fresh process; confirmed empty store + default clock on boot. A ~90-assertion end-to-end script passed covering: envelope/error formats, auth 401/403, policy overlap with adjacency, prescription verify, order create/qualify (provisional math: ded 10000 + coins 4000 = 14000), inclusive prior-auth threshold (50000 ≥ 50000), shipment PA gate, delivery cascade (schedule `next_eligible_date` = delivery + 90d, member aggregates), claim SoD/imbalance/balanced remit/void reversal/re-file after void, PA pend→resubmit→approve→lazy EXPIRED at shipment, resupply window/cap/ROLLING recompute, schedule OCC 412 + frequency recompute, resupply cancel rollback, warranty replace cascade, lazy schedule ENDED at benefit-period end.

One bug found and fixed during verification: claim creation after a void was rejected because the guard didn't accept the post-void `CLAIM_FILED` billing state; now `CLAIM_FILED` is accepted on both the PA and non-PA paths (per PRD §3.6 "leaving the order claimable once more").

## Step 7: Run Tests and Iterate — 2026-08-10T06:29:04.901Z

All 8 rounds pass 98/98. Clean sweep — exiting.

**Summary**

- **Iterations run:** 2 (first sweep: 3 deterministic failures × all 8 rounds; second sweep: 98/98 in all 8 rounds).
- **Tests deleted:** none. All three failures were test-artifact bugs, not PRD-silent assertions.
- **Fixes applied to `test_helpers/`:** none — fixtures and header builders were PRD-consistent; the bugs were all in the test layer.
- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_0967_breast_pump_maternity_dme/test_suite/test_03_prescription_lifecycle.py` — added missing `setup_pending_order_verified` to the `test_helpers` import block (the helper existed and was exported; `test_resubmit_from_verified_rejected` used it un-imported, causing `NameError`).
  - `/home/ubuntu/github/CodingPRD/tasks/task_0967_breast_pump_maternity_dme/test_suite/test_07_shipment_delivery.py` — `test_skip_transition_label_created_to_delivered_rejected`: changed expected `fulfillment_status` from `QUALIFIED` to `SHIPPED`; PRD §3.4 verbatim ("A passing shipment cascades the pump order `QUALIFIED → SHIPPED`") means shipment creation — not the advance — moves the order, so the rejected skip transition correctly leaves it `SHIPPED`.
  - `/home/ubuntu/github/CodingPRD/tasks/task_0967_breast_pump_maternity_dme/test_suite/test_08_claims_remittance.py` — `test_submitter_cannot_remit_even_with_imbalanced_amounts`: readback of the claim switched from `care_coordinator_headers` to `make_insurance_specialist_headers("ins-1")`; PRD §4 authorizes only `Member, InsuranceSpecialist, BillingSpecialist, PlatformAdmin` for `GET /dme/claims/{id}`, so the 403 `ERR_FORBIDDEN` was the implementation correctly enforcing the role list (the SoD assertion itself was passing).
- **Fixes applied to `implementation/`:** none — the implementation was PRD-faithful in all three cases.

Orchestrator verification: all 8 `results.{1..8}.json` files on disk report 98/98 passed, 0 failed.

## Step 8: Finalize PRD — 2026-08-10T06:30:11.229Z

`PRD_FINALIZED.md` produced at `/home/ubuntu/github/CodingPRD/tasks/task_0967_breast_pump_maternity_dme/workspace/PRD_FINALIZED.md`. It is a verbatim copy of `PRD.md` — zero edits were warranted.

**Line counts / %-delta:** PRD.md 328 lines, PRD_FINALIZED.md 328 lines, 0% delta.

**Changes:** none. Every `<step_7_diff>` item traced to a pure test-artifact bug where the PRD already uniquely determined the behavior and `implementation/` was PRD-faithful — Step 7 itself recorded zero `implementation/` fixes and zero test deletions. Per the hard scope ("Patch only when impl pinned a choice PRD left open, or impl mismatched PRD"), there was nothing to pin.

### Per-item verification (pre-edit analysis; all resulted in no edit)

1. **§3.1 prescription resubmit** — test bug was a missing `setup_pending_order_verified` import (`NameError`); the underlying assertion (`test_resubmit_from_verified_rejected`) never ran.
   - (a) Subject: resubmit precondition — which source states are accepted.
   - (b) Paths enumerated: `implementation/routes_core.py:248-261` (`resubmit_prescription`: requires `status == "REJECTED"`, else `ERR_INVALID_STATE` 409, then lazy expiry check and `REJECTED → PENDING_VERIFICATION` with `rejection_reason` cleared); cross-checked `verify`/`reject` handlers nearby and §2.8 item 6 (state preconditions → `ERR_INVALID_STATE`).
   - (c) No wording needed: PRD §3.1 already pins "moving `REJECTED → PENDING_VERIFICATION`" and §2.8/§5 pin `ERR_INVALID_STATE` 409 for state-machine violations, so resubmit-from-VERIFIED rejection is fully determined.

2. **§3.4 shipment creation cascade + skip-transition rejection** — test expected order left `QUALIFIED` after a rejected `LABEL_CREATED → DELIVERED` advance; correct value is `SHIPPED`.
   - (a) Subject: when the pump order moves `QUALIFIED → SHIPPED`, and legality of skipping carrier statuses.
   - (b) Paths enumerated: `implementation/routes_ops2.py:150-205` (`create_shipment` sets `order["fulfillment_status"] = "SHIPPED"` at creation, after the PA gate); `routes_ops2.py:227-232` (`_ADVANCE_ALLOWED` permits only `LABEL_CREATED→{IN_TRANSIT,LOST}`, `IN_TRANSIT→{OUT_FOR_DELIVERY,LOST}`, `OUT_FOR_DELIVERY→{DELIVERED,RETURNED}`; skips → `ERR_INVALID_STATE` 409 at line 240); delivery cascade at `routes_ops2.py:244-276` (only acts when order is already `SHIPPED`). Also checked warranty-replacement creation path doesn't touch order status.
   - (c) No wording needed: PRD §3.4 verbatim "A passing shipment cascades the pump order `QUALIFIED → SHIPPED`" and the enumerated stepwise transitions already determine both behaviors.

3. **§4 `GET /dme/claims/{id}` role list** — test readback used `care_coordinator_headers` and got 403; implementation correctly enforced the role list.
   - (a) Subject: authorized roles for claim reads.
   - (b) Paths enumerated: `implementation/routes_ops.py:38` (`CLAIM_READ_ROLES = ["Member", "InsuranceSpecialist", "BillingSpecialist", "PlatformAdmin"]`), consumed by both `get_claim` (`routes_ops2.py:345-350`) and `list_claims` (`routes_ops2.py:353-355`), each followed by member-ownership checks.
   - (c) No wording needed: PRD §4 endpoint table pins exactly this four-role list for both `GET /dme/claims/{id}` and `GET /dme/claims`; `CareCoordinator` exclusion is explicit and matches impl.

No pre-edit searches were required beyond the verification above because no edit was committed — each would-be edit site was confirmed to already match the implementation exactly.

## Step 9: Complete PRD — 2026-08-10T06:35:33.890Z

All pins verified present (the "MISSING" line was a grep-pattern artifact — the actual wording "a duplicate is rejected with `ERR_VALIDATION`" is in place). Work complete.

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_0967_breast_pump_maternity_dme/workspace/PRD_COMPLETED.md`

**Source vs result:** `PRD_FINALIZED.md` 328 lines / 52,193 chars → `PRD_COMPLETED.md` 329 lines / 56,587 chars (char-delta +4,394). All changes are in-paragraph inserts/revisions; no new sections.

**Counts:** 26 changes total — 24 ambiguity-pins, 2 mismatch-revisions.

**Changes (one bullet each):**

- §2.1 — insert — ambiguity — Member list endpoints implicitly scope to own records (shipments by source-order ownership); a `member_id` filter naming another member → ERR_OWNERSHIP_VIOLATION — implementation/middleware.py:190-201, implementation/routes_ops2.py:216-218
- §2.8 — insert — mismatch — ownership-vs-existence resolution order: body-carried/path-member-id ownership checked before lookup; path-loaded resource ownership checked after existence (404 first) — implementation/routes_core.py:53-55 vs 131-132, implementation/routes_supply.py:184-190
- §2.8 — insert — ambiguity — ERR_STALE_VERSION evaluated after request-shape, before state checks — implementation/routes_ops.py:155-163, implementation/routes_supply.py:51-67
- §2.2 — revise — ambiguity — `api_request_timestamp` is wall-clock, not logical clock — implementation/response.py:10-12
- §2.2 — insert — ambiguity — fallback errors ERR_NOT_FOUND (404), ERR_METHOD_NOT_ALLOWED (405), ERR_INTERNAL (500) — implementation/app.py:25-35
- §2.3 — revise — ambiguity — non-integer/out-of-range limit or negative offset → ERR_VALIDATION 400; `created_at` ties broken by insertion order — implementation/middleware.py:164-178
- §2.4 — revise — ambiguity — `created_at`/`updated_at` stamped from the logical clock — implementation/db.py:43-45, implementation/services.py:18-24
- §3.1 — revise — ambiguity — duplicate member email → ERR_VALIDATION 400 — implementation/routes_core.py:35-36
- §3.1 — revise — ambiguity — new Member also starts with `active_schedule_count` 0 — implementation/routes_core.py:45
- §3.1 — revise — ambiguity — policy defaults pinned: `deductible_cents` 0, `coinsurance_pct` 0, `oop_max_cents` 0, `upgrade_coverage` false — implementation/routes_core.py:87-92
- §3.2 — revise — ambiguity — duplicate `sku` → ERR_VALIDATION — implementation/routes_core.py:278-279
- §3.2 — insert — ambiguity — every catalog item carries the full field set; type-irrelevant fields default (STANDARD/0/0/null; false/0) — implementation/routes_core.py:272-291
- §3.2 — revise — ambiguity — `covered_under_resupply` filter takes literal `true`/`false`, else ERR_VALIDATION — implementation/routes_core.py:306-313
- §3.2 — insert — ambiguity — order creation does not check item is PUMP type nor prescription status; only pump_type agreement — implementation/routes_ops.py:82-88
- §3.2 — insert — ambiguity — provisional figures, upgrade-fee snapshot, and `prior_auth_required` start at zero/false until qualification — implementation/routes_ops.py:97-100
- §3.3 — insert — ambiguity — no cap on prior authorizations per order; each submission creates a fresh PA — implementation/routes_ops2.py:25-54
- §3.3 — insert — ambiguity — APPROVED missing `approved_until` → ERR_VALIDATION; PENDED accepted only from SUBMITTED — implementation/routes_ops2.py:92-95
- §3.4 — insert — ambiguity — `approved_until` inclusive at shipment; among several lapsed APPROVED PAs the most recently created flips to EXPIRED — implementation/routes_ops2.py:170-179
- §3.5 — revise — ambiguity — schedule PATCH naming current status → ERR_INVALID_STATE; `frequency_days` must be int ≥ 1 — implementation/routes_supply.py:55-67
- §3.5 — insert — mismatch — benefit-period check evaluated before resupply-window check (both failing → schedule ENDED + ERR_BENEFIT_PERIOD_ENDED) — implementation/routes_supply.py:102-112
- §3.6 — revise — ambiguity — resupply-order claim derivation (member from resupply order, policy via originating pump order); `claim_number` format `CLM-` + six-digit zero-padded sequence; resupply orders carry no `billing_status` so billing cascades apply to pump-order claims only — implementation/routes_ops2.py:317-327, 339-341
- §3.6 — insert — ambiguity — balance invariant enforced only on APPROVED outcomes; DENIED remittance stores only `remitted_by_user_id`/`remitted_at` and leaves adjudicated fields unset — implementation/routes_ops2.py:393-425
- §3.7 — revise — ambiguity — warranty months added calendar-wise with day clamped to month length; filing on the final day allowed (strictly-past comparison) — implementation/services.py:114-119, implementation/routes_supply.py:194
- §3.7 — revise — ambiguity — replacement shipment `tracking_number` format `WR-` + 12 uppercase hex chars — implementation/routes_supply.py:281
- §3.8 — insert — ambiguity — pump-order cancellation leaves `billing_status` unchanged — implementation/routes_ops.py:256
- §2.10 — revise — ambiguity — member `version` advances only when an aggregate actually changes value — implementation/services.py:108-111
