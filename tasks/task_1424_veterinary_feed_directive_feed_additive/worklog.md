# Worklog — task_1424_veterinary_feed_directive_feed_additive

## Step 1: Create Task Directory — 2026-08-13T05:56:00.000Z

Task directory `tasks/task_1424_veterinary_feed_directive_feed_additive/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher (Step 1 treated as DONE per invocation args).

## Step 2: Generate Scaffold — 2026-08-13T06:25:00.000Z

All 9 difficulty rules have exactly 2 instances each (18 total). All FKs reverse-reachable. Lint is clean.

Final summary:

## Summary

Generated the complete scaffold for `task_1424_veterinary_feed_directive_feed_additive/` at harder-than-expert difficulty.

### Files written (all three required)
- `/home/ubuntu/github/CodingPRD/tasks/task_1424_veterinary_feed_directive_feed_additive/SCAFFOLD.yaml` — §1.0–§1.7, 1470 lines
- `/home/ubuntu/github/CodingPRD/tasks/task_1424_veterinary_feed_directive_feed_additive/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — §1.8, 18 instances across 9 rules
- `/home/ubuntu/github/CodingPRD/tasks/task_1424_veterinary_feed_directive_feed_additive/SCAFFOLD_CORNER_DESIGN.yaml` — §1.9, 22 instances (20 active + 2 excluded stubs)

### Scaffold statistics
- **14 entities**: VeterinaryClinic, Veterinarian, Producer, AnimalGroup, VfdDrug, VcpVerification, VfdAuthorization, FeedMill, FeedOrder, FeedShipment, WithdrawalPlan, DistributorAcknowledgment, ResidueCase, AuditBundle
- **62 endpoints** (including `POST /vfd/_clock/set_current_utc` with default `2026-08-01T00:00:00Z`)
- **23 error codes** covering auth, state, safety, temporal, fiscal, referential, constraint, OCC
- **7 calculations** (incl. dual-variant `provisional_market_date` forward-looking vs `final_market_date` chronological; round-per-tier-then-sum `compliance_penalty`; interval-merge `audit_required_records`)
- **8 state machines** with cycle (Veterinarian ACTIVE↔SUSPENDED), branching (FeedOrder fork from SUBMITTED), parallel dimensions (WithdrawalPlan PROVISIONAL→FINALIZED|VIOLATED), and 4-deep transitive cascades (Vet suspend → VFD EXPIRED → FeedOrder CANCELLED → mill pending_count decrement)
- **18 ordered validations** covering priority pairs (state vs safety, safety vs fiscal)
- **4 roles** (Inspector opaque; Veterinarian/FeedMillOperator/Producer entity-backed) with strict segregation of duties
- **2 concurrency rules** (OCC on VfdAuthorization.version for supersede and validate)

### Difficulty rule coverage (§1.8, ≥2 per rule, all differentiated)
1. dual_variant_calc — WithdrawalPlan provisional vs final; VFD remaining_animal_count forward vs settled
2. combinatorial_formula — mode (b) tiered marginal rounding; mode (a) 3-input max
3. non_linear_state_machine — Veterinarian cycle; FeedOrder branching
4. transitive_cascade — depth-4 vet-suspend cascade; depth-3 audit-deficient cascade
5. priority_pair_validation_conflict — state vs safety; safety vs fiscal
6. boundary_precision_check — VFD expiration exact-timestamp; audit empty-set zero
7. cross_entity_state_dependency — FeedOrder×VCPR; FeedOrder×DistributorAck
8. resource_temporal_overlap — point-in-interval VCPR; interval-intersection audit window
9. compensating_invariant — VFD quota conserved; clinic compliance_score conserved

### Lint verdict
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(62 endpoints, 14 entities, 18 difficulty instances, 22 corner instances, 343 calls scanned)

## Step 3: Copy Shared Files — 2026-08-13T06:26:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1424_veterinary_feed_directive_feed_additive/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T06:33:00.000Z

All three hard contracts pass. PRD generation is complete.

**Report**

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1424_veterinary_feed_directive_feed_additive/workspace/PRD.md`.

Structure: 1 Introduction (3 paragraphs from regulatory-chokepoint angle), §2 with 10 subsections (RBAC, verbatim §2.2 response structure, pagination, resource identity, logical clock, withdrawal precision, OCC, VFD quota accounting, compliance score/audit-ready, audit window semantics), §3 with 11 subsections organized by entity lifecycle and cross-cutting concerns (onboarding, VCPR, VFD issuance/supersession, expiration cascade, order submission/validation/rejection, shipping/delivery/withdrawal, cancellation, residue cases, audit bundles, distributor acknowledgments, read access), §4 endpoint table (61 endpoints, 4 columns), §5 error catalogue (23 errors, 2 columns).

Hard Contracts:
- **Contract 1 (Field-Name Coverage)**: 75 required, 75 present, 0 missing — PASS (two names caught on first pass — `clinic_id`, `severity_tier` — and patched in)
- **Contract 2 (Rule Coverage)**: All priority-ordered validations, both OCC rules (with `expected_vfd_authorization_version`, `ERR_STALE_VERSION`, HTTP 412 named), all state transitions with preconditions and side effects, all six calculations with precise prose formulas (provisional/final market date, remaining quota, residue severity tiers 2.0/5.0 boundaries, tiered compliance penalty with rates 50/150/400 and flat 100 and per-tier round-then-sum, audit interval merge with half-open window semantics, audit-readiness threshold 700), all entity field defaults (compliance_score 1000, prohibited_extra_label pinned true, extra_label_intended default false, etc.) — PASS
- **Contract 3 (§3 Path Purity)**: 406 backticked tokens scanned in §3, 0 violations (no `/`-prefixed paths, no bare HTTP methods, no method+path combinations) — PASS

## Step 5: Generate Unit Tests — 2026-08-13T07:05:00.000Z

Generation complete. Summary of what was produced for `tasks/task_1424_veterinary_feed_directive_feed_additive/`:

**Stage 1 — `test_helpers/` (9 files, all compile-verified and import-tested)**
- `types.py` — 14 entity TypedDicts (all carry common fields per PRD §2.4), 12 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (48 methods)
- `api_errors.py` — all 23 error IDs + HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions plus `parse_timestamp`/`assert_timestamp_equals` (handles date-only vs millisecond forms) and VFD-quota/clinic invariants
- `factories.py` — input-field-only factories with auto-unique constrained fields (license/PIN/FDA/drug codes)
- `constants.py` — 1000/700 score constants, tier rates 50/150/400 + flat 100, 6-month VFD cap, default clock
- `test_users.py` — Inspector opaque constant + mandatory `make_veterinarian/feed_mill_operator/producer_headers(entity_id)` builders for the three entity-backed roles
- `fixtures.py` — composite chain builders: `setup_vfd_chain`, `setup_order_chain`, `setup_validated_order`, `setup_shipped_order`, `setup_delivered_order`, `setup_case_under_investigation`, `setup_audit_bundle`, with correct identity threading throughout

**Stage 2 — `test_suite/` (conftest + 8 files, 54 tests)**
- test_01 registry/onboarding (6), test_02 access control (4), test_03 VFD issuance & supersede (8), test_04 feed-order lifecycle (13), test_05 withdrawal projections (5), test_06 expiration & cascades (7), test_07 residue & compliance (4), test_08 audit bundles (7)
- Coverage: all 22 non-stub corner instances ≥1 test; 16 of 18 difficulty instances ≥2 tests; both corner stubs verified to resolve to real difficulty instances and left untranslated

**Two instances skipped under the PRD-first filter (gaps left as gaps):**
1. `Difficulty/priority_pair_validation_conflict/safety_vs_fiscal_vcpr_missing_and_quota_exceeded` — the index asserts ERR_VCPR_NOT_VERIFIED wins over ERR_VFD_QUOTA_EXCEEDED, but PRD §3.5's explicit priority order lists quota fourth and VCPR eighth ("earlier failures mask later ones"), so the asserted outcome contradicts the PRD.
2. `Difficulty/resource_temporal_overlap/vcpr_validity_interval_must_cover_vfd_issuance` — asserted ERR_VCPR_NOT_VERIFIED at clock == `expires_on` requires inclusive-expiry semantics; PRD §2.5 ("now in the past", strict) and §3.2 ("when the logical clock reaches", inclusive) contradict each other at exact equality, so success-vs-failure is not uniquely derivable.

**Adaptations made during translation (PRD-faithful, noted in docstrings):**
- `vfd_expiration_exact_boundary`: the exact-equality validate rejection is asserted as HTTP 409 via `validate_error_is_one_of([ERR_VFD_EXPIRED, ERR_VFD_NOT_USABLE, ERR_INVALID_STATE])` (error-precedence silence pattern — §2.5 vs §3.4 cascade timing at equality is ambiguous); the −1s success and +1s EXPIRED-cascade assertions are exact.
- `occ_stale_version_on_supersede`: setup advances the VFD version via a feed-order validation (keeping the VFD supersedable in PARTIALLY_USED) so the stale version is the only failing precondition, instead of the index's double-supersede (which would leave precedence between the unnamed state-check error and ERR_STALE_VERSION ambiguous).
- `feedorder_validate_requires_vcpr_active`: test 1 lapses the VCPR via the clock (§3.2 "no further side effects") so ERR_VCPR_NOT_VERIFIED is the sole failing check; test 2 uses the revoke path and asserts the §3.2 cascade (VFD EXPIRED, order CANCELLED/`VFD_EXPIRED`).
- All audit-window tests use forward-only clock moves (PRD §2.5 says the inspector may "advance" the clock).
- Status-reversal assertions (`PARTIALLY_USED`→`ISSUED` after cancel) were dropped — no PRD transition supports them.

Final audit: every test has exactly one valid `Design:` tag, every PRD citation verbatim-greps against PRD.md, no skip/xfail markers anywhere, all files compile.

## Step 6: Generate Implementation — 2026-08-13T07:05:00.000Z

## Report

Generated a complete Python + Flask implementation for `task_1424_veterinary_feed_directive_feed_additive` at `/home/ubuntu/github/CodingPRD/tasks/task_1424_veterinary_feed_directive_feed_additive/workspace/implementation/`.

### File layout

```
implementation/
├── start.sh                 # Foreground launcher, guards pip install, execs app.py
├── requirements.txt         # flask>=2.2,<4
├── app.py                   # Entry point: Flask app, blueprint registration, error handlers
├── db.py                    # In-memory Store (dicts keyed by id); no persistence, no seeding
├── errors.py                # ApiError class + all 23 error IDs from §1.6
├── response.py              # Envelope per PRD §2.2 (meta/response_type/data; pagination fields in meta)
├── middleware.py            # X-User-Role/X-User-ID extraction + role gating per PRD §2.1
├── clock.py                 # Logical clock, default 2026-08-01T00:00:00Z
├── util.py                  # ISO 8601 parse, minute truncation, entity stamping (id/created_at/updated_at/version)
├── services/
│   └── core.py              # Cascades, quota recompute, withdrawal math, severity/penalty calcs, audit_ready, audit window
└── routes/
    ├── onboarding.py        # clinics, veterinarians, producers, animal groups, drugs, feed mills
    ├── vcp.py               # VCP verifications
    ├── vfd.py               # VFD authorizations (issue + supersede with OCC)
    ├── feed_orders.py       # feed orders (submit/validate/reject/cancel/ship)
    ├── shipments.py         # feed shipments (deliver/return/reject-receipt) + withdrawal plans
    ├── acks.py              # distributor acknowledgments
    ├── residue.py           # residue cases (open-investigation/confirm/dismiss)
    ├── audit.py             # audit bundles (record-produced/close/mark-deficient)
    └── clock_routes.py      # POST /vfd/_clock/set_current_utc
```

### Key implementation decisions traced to PRD/SCAFFOLD

- **Response envelope**: `meta` (api_request_id, api_request_timestamp; lists add limit/offset/total_count/has_more), `response_type`, `data`. Errors carry `error_id`+`message` inside `data`.
- **Auth**: priority 1 = `X-User-Role` in {Inspector, Veterinarian, FeedMillOperator, Producer} → ERR_UNAUTHENTICATED; priority 2 = role-on-endpoint → ERR_UNAUTHORIZED; priority 3 = entity-backed identity (vet on VFD/VCPR, producer on order/shipment, mill on order) → ERR_FORBIDDEN.
- **Logical clock**: separate from wall clock; `POST /vfd/_clock/set_current_utc` advances it and re-evaluates VFD/VCPR expirations, firing the full FeedOrder cancellation cascade.
- **OCC**: `expected_vfd_authorization_version` required on VFD-supersede and FeedOrder-validate; mismatch → ERR_STALE_VERSION (412).
- **Validation ordering** on `POST /feed-orders/{id}/validate` follows PRD §3.5's eight-step order exactly: VFD_NOT_USABLE → VFD_EXPIRED → PRODUCER_SUSPENDED → VFD_QUOTA_EXCEEDED → SPECIES_CLASS_MISMATCH → EXTRA_LABEL_USE → RESIDUE_CASE_OPEN → VCPR_NOT_VERIFIED, then the OCC check.
- **Withdrawal math**: `provisional_market_date = max(now + withdrawal_hours, earliest_market_date)` truncated to whole minute; `final_market_date = last_feed_consumed_at + withdrawal_hours` truncated likewise. If final > earliest_market_date → plan VIOLATED and an OPEN ResidueCase is auto-created with `residue_ppb=None`.
- **Compliance penalty**: per-tier marginal amounts rounded half-up to integer (via `Decimal.quantize(ROUND_HALF_UP)`) *before* summing, then a flat 100 added. Tiers: ≤1→0; 1–2 ×50; 2–5 ×150; >5 ×400. Verified: ratio 6.0 → 50+450+400+100 = 1000.
- **Severity tiers**: ratio strictly <2 → TIER_1; <5 → TIER_2; else TIER_3.
- **Audit window**: half-open `[window_start, window_end)`; record qualifies iff `created_at < window_end` AND (`terminal_at IS NULL` OR `terminal_at >= window_start`). Counts VFDs + orders + shipments + acks (acks of mills that appear on any included order).
- **Cascade**: VFD → EXPIRED/REVOKED/SUPERSEDED cancels SUBMITTED/VALIDATED orders with `rejection_reason="VFD_EXPIRED"`, decrements `FeedMill.pending_order_count` once per VALIDATED order, recomputes remaining quota, leaves orphaned PROVISIONAL WithdrawalPlan behind.
- **Vet discipline**: suspend/revoke cascades VFDs → EXPIRED; reinstate does not resurrect.
- **Audit deficiency**: marks producer SUSPENDED and cascades producer's non-terminal VFDs → EXPIRED.
- **No entity seeding at startup**; all dicts empty on boot; every boot re-imports cleanly for `--isolation per-test-server`.

### Smoke verification (server booted on PORT, killed/restarted cleanly)

- Onboarding happy path: clinic/vet/producer/group/drug/mill/ack/VCPR/VFD all 201 with correct system fields (`compliance_score=1000`, `audit_ready=true`, `status=ACTIVE`, `prohibited_extra_label=true`, `pending_order_count=0`, `remaining_animal_count=authorized`).
- Order lifecycle: SUBMITTED → VALIDATED (withdrawal plan created PROVISIONAL with correct provisional date; VFD remaining debited 50→30; version 1→3; mill pending 0→1) → SHIPPED → DELIVERED (plan FINALIZED with final = last_feed + 72h).
- Violation fork: last_feed+240h > earliest_market_date → plan VIOLATED; auto OPEN ResidueCase; `open-investigation` → `confirm` with ratio 6.0 → severity TIER_3, deduction 1000, clinic score 1000→0, audit_ready flips to false.
- Supersede OCC: stale expected_version → 412 ERR_STALE_VERSION; correct version → new VFD ISSUED with independent count, old VFD SUPERSEDED, remaining zeroed, superseded_by_id set, version incremented once.
- Audit: required_record_count computed; close with shortfall → ERR_AUDIT_INCOMPLETE; mark-deficient → producer SUSPENDED, producer's VFDs cascade EXPIRED.
- Auth: missing role → 401 ERR_UNAUTHENTICATED; wrong role → 403 ERR_UNAUTHORIZED; unknown id → 404 ERR_NOT_FOUND.

## Step 7: Run Tests and Iterate — 2026-08-13T07:14:00.000Z

## Summary

- **Iterations run**: 2 (sweep 1: diagnose; sweep 2: verify clean).

- **Tests deleted**: none.

- **Fixes applied to `test_helpers/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1424_veterinary_feed_directive_feed_additive/test_helpers/fixtures.py` — fixture `submit_order`: when `intended_use_label` is not explicitly overridden, the fixture now fetches the VFD's drug and defaults the label to the drug's `label_name`. **Why**: all 29 failures in sweep 1 shared one setup error — `HTTP 422 ERR_EXTRA_LABEL_USE` at order submission. PRD §3.5 requires verbatim: "The `intended_use_label` must match the label indications of the VFD's drug", and the drug's only label-indication field per PRD §3.1 is `label_name`. The factory defaulted `intended_use_label` to `"label use"` against a drug whose `label_name` defaults to `"Test Medication"`, so every fixture-built order violated the PRD's lawful-order precondition and the implementation correctly rejected it. The new default passes under both plausible readings of "match" (equality or containment); tests probing `ERR_EXTRA_LABEL_USE` still override the field explicitly.

- **Fixes applied to `implementation/`**: none. The implementation's extra-label guard (and all other checks) traced to verbatim PRD sentences and was correct; the failures were entirely a test-side fixture bug.

- **Final state**: all 8 parallel rounds pass 54/54 under `--isolation per-test-server`.

- **Observation (no action taken, no test coverage exists)**: `workspace/implementation/routes/vfd.py` fires the order-cancellation cascade (`cascade_vfd_terminal`) on supersede, while PRD §3.3 says non-terminal orders bound to the old VFD "remain bound to it but cannot be further validated" and §3.4 limits the cancellation cascade to expire/revoke/cascade-into-EXPIRED. No test exercises order state after supersede, so both readings pass today; flagged for future hardening only.

## Step 8: Finalize PRD — 2026-08-13T07:22:00.000Z

Done. `PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_1424_veterinary_feed_directive_feed_additive/workspace/PRD_FINALIZED.md` with exactly two edits, both traced to `<step_7_diff>` items.

## Summary

**Line counts / delta**: PRD.md 271 lines → PRD_FINALIZED.md 271 lines (0% delta; both edits are inline within existing paragraphs, no new sections).

**Changes**:
- §3.5 — revise — pinned the previously undetermined "match" semantics for `intended_use_label`: the drug's labeled identity for this check is its `label_name`, and the label matches when `label_name` appears within the submitted `intended_use_label` text (substring containment, not equality) — `implementation/routes/feed_orders.py:17-23` (`_drug_label_indications_match`: `drug.get("label_name", "") in intended_use_label`), enforced at submission (`feed_orders.py:55`) and validation check #6 (`feed_orders.py:146`).
- §3.3 — revise — replaced the incorrect "non-terminal `FeedOrder`s … remain bound to it but cannot be further validated" with the actual behavior: supersession fires the §3.4 cancellation cascade on the old VFD (SUBMITTED/VALIDATED orders → `CANCELLED` with `rejection_reason` = `VFD_EXPIRED`, mill `pending_order_count` decremented per previously-`VALIDATED` order, `WithdrawalPlan` orphaned in `PROVISIONAL`); cancelled orders remain bound; orders past `VALIDATED` (`SHIPPED`/`DELIVERED`) are unaffected — `implementation/routes/vfd.py:131`, `implementation/services/core.py:98-126`.

**Per-edit pre-edit search log**:

Edit 1 (§3.5 match semantics):
- (a) Subject: meaning of "match" between `intended_use_label` and the drug's label indications.
- (b) Paths enumerated: `_drug_label_indications_match` (`feed_orders.py:17-23`); submission guard (`feed_orders.py:54-57`); validation guard #6 (`feed_orders.py:145-148`); drug registration storing `label_name` verbatim with no normalization (`onboarding.py:252-264`); issuance extra-label guard (`vfd.py:60-62`), which checks only the `extra_label_intended` flag and never `intended_use_label`. Grep over all `*.py` confirmed no other `intended_use_label`/`label_name` consumers.
- (c) Wording scoped to "for this check" so it defines the submission/validation label comparison only and makes no claim about the issuance-time flag guard described in §3.3; "appears within … text" chosen over "equals" to exactly reflect substring containment at both call sites.

Edit 2 (§3.3 supersede cascade):
- (a) Subject: order state (and related side effects) when a VFD is superseded.
- (b) Paths enumerated: supersede flow (`vfd.py:129-135`); shared cascade `cascade_vfd_terminal` and `_cancel_order_for_vfd_cascade` (`core.py:98-126`) and all its callers — VFD revoke (`vfd.py:176`), vet suspend/revoke (`onboarding.py:126,149`), VCPR revoke (`vcp.py:80`), audit mark-deficient (`audit.py:94`), clock advance (`core.py:155-161`); `recompute_vfd_remaining` (`core.py:83-91`); the non-cascade cancellation paths (explicit cancel `feed_orders.py:231-244`; shipment return/reject-receipt `shipments.py:106,121`); terminal-status table (`core.py:252-257`); validation gating requiring `SUBMITTED` (`feed_orders.py:115`).
- (c) Wording adjustments: (i) said "fires the same feed-order cancellation cascade described in §3.4" rather than redefining a new cascade, keeping consistency with all six cascade callers; (ii) deliberately omitted any quota-return claim for supersede, since the impl recomputes then zeroes `remaining_animal_count` (`vfd.py:132`), making a return unobservable — §2.8's existing "supersede … zeroes" sentence stays verbatim and uncontradicted; (iii) explicitly kept "remain bound" (impl never rewrites `vfd_authorization_id`) and added that `SHIPPED`/`DELIVERED` orders are unaffected (`core.py:101-102` early-returns for non-SUBMITTED/VALIDATED), so the sentence covers the full "non-terminal" population the old wording referenced; (iv) did not touch §3.4's "three ways / EXPIRED (or REVOKED)" framing, since §3.3 now states the supersede cascade explicitly and §3.4's enumeration remains accurate for its own three cases.

**No edit made for**: the `test_helpers/fixtures.py` fix itself (pure fixture bug — PRD already required the extra-label match verbatim; only the impl-pinned "match" semantics above warranted pinning). No test deletions and no implementation fixes were listed in Step 7, so no other edits were in scope.

## Step 9: Complete PRD — 2026-08-13T07:45:00.000Z

Done. `PRD_COMPLETED.md` produced at `/home/ubuntu/github/CodingPRD/tasks/task_1424_veterinary_feed_directive_feed_additive/workspace/PRD_COMPLETED.md`.

**Source vs output**: `PRD_FINALIZED.md` (271 lines / 41,325 chars) → `PRD_COMPLETED.md` (273 lines / 47,272 chars); char-delta **+5,947**, 26 diff hunks.

**Counts**: ambiguity-pins: 19, mismatch-revisions: 7.

Changes (all inline; no new sections):

- §2.1 — revise — mismatch — "Issuing a VFD requires the caller to be a veterinarian" weakened the real rule; now enumerates all impl identity checks (VCPR record/VFD issue = payload `vet_id`; order submit = path mill; validate/reject/ship = order's `feed_mill_id`; record-produced = bundle's producer) — `vfd.py:56`, `vcp.py:27`, `feed_orders.py:41,105,207,251`, `audit.py:60`
- §2.1 — insert — ambiguity — missing `X-User-ID` is not an authentication failure; only the role header is validated — `middleware.py:14-18`
- §2.2 — insert — ambiguity — generic `ERR_INVALID_REQUEST`(400) family for missing/malformed fields, enums, timestamps; unknown path → `ERR_NOT_FOUND`(404); unsupported method → `ERR_INVALID_REQUEST`(400) — `util.py:52-84`, `app.py:34-40`
- §2.3 — insert — ambiguity — pagination param violations → `ERR_INVALID_REQUEST`; sort tie-break `id` ascending; `has_more` = `offset + returned < total_count` — `onboarding.py:21-34`, `response.py:34`
- §2.4 — revise — mismatch — "optional fields omitted" replaced: never-assigned fields are omitted, explicitly-null fields serialize as `null` — `residue.py:28-38`, `shipments.py:79-89`
- §2.4 — insert — ambiguity — body required-field/type checks fire after path lookups but before body-reference existence — `vfd.py:33-53`, `feed_orders.py:29-38`
- §2.5 — revise — mismatch — clock expiry fires at `now >= expiration_date` (not strictly "in the past") and only for `ISSUED`/`PARTIALLY_USED` VFDs, `ACTIVE` VCPRs — `core.py:155-167`
- §2.5 — insert — ambiguity — clock endpoint accepts any parseable target, no monotonicity check — `clock_routes.py:18-20`
- §2.8 — insert — mismatch — within a VFD-driven cascade, quota return is one recomputation and `version` increments once for the whole cascade, not per cancelled order — `core.py:114-126`
- §2.8 — insert — ambiguity — return/reject compensation adds back to current `remaining_animal_count` even on terminal (e.g. superseded) VFDs — `feed_orders.py:221-228`
- §2.9 — revise — mismatch — `audit_ready` is recomputed on case open/dismiss/confirm and *does* return to true when both conditions hold again (PRD said it never flips back) — `core.py:223-245`, `residue.py:40,126`, `shipments.py:91`
- §2.10 — insert — ambiguity — terminal timestamp = `updated_at`; terminal-status sets enumerated per entity — `core.py:252-270`
- §3.1 — insert — ambiguity — no `X-User-ID` ownership check when a Producer registers an animal group — `onboarding.py:205-208`
- §3.2 — insert — ambiguity — VCPR recording requires vet `ACTIVE` (else `ERR_VET_INACTIVE` 409); `revocation_reason` recorded on the VCPR — `vcp.py:29-31,78`
- §3.3 — revise — ambiguity — six-month duration = calendar-month arithmetic with day clamping, time-of-day preserved, exact boundary accepted — `vfd.py:76-86`
- §3.3 — insert — ambiguity — identity check position (after entity loads, before business checks) and business-check evaluation order (extra-label → species/class → VCPR → duration → producer → vet), which differs from prose order — `vfd.py:56-96`
- §3.3 — insert — ambiguity — supersede checks run after all issuance checks, ordered: old-VFD state → presence/type of `expected_vfd_authorization_version` → OCC comparison — `vfd.py:99-112`
- §3.4 — insert — ambiguity — reinstate requires `SUSPENDED` (else `ERR_INVALID_STATE`) — `onboarding.py:130-138`
- §3.5 — insert — ambiguity — order producer/VFD producer mismatch rejected with `ERR_INVALID_REQUEST` (400) — `feed_orders.py:45-46`
- §3.5 — insert — ambiguity — label match is a case-sensitive substring test — `feed_orders.py:17-23`
- §3.5 — insert — ambiguity — validation pre-checks (identity, `expected_vfd_authorization_version` presence/type, `SUBMITTED` state) and OCC comparison evaluated last, after all eight checks — `feed_orders.py:105-116,166-169`
- §3.5 — insert — ambiguity — quota debit and status transition are separate mutations; `version` +2 when validation also flips status — `feed_orders.py:186-193`
- §3.5 — revise — mismatch — reject-order error priority: state check fires before missing-`rejection_reason` check (PRD listed reason first) — `feed_orders.py:209-214`
- §3.6 — insert — ambiguity — ship gating checks evaluated state → expiration → acknowledgment, before `tons_shipped` payload validation — `feed_orders.py:253-271`
- §3.6 — insert — ambiguity — auto-opened ResidueCase field values (`tolerance_ppb`, `investigator_id`, `severity_tier` null; `penalty_score_deduction` 0) — `shipments.py:79-89`
- §3.8 — revise — ambiguity — confirmed status named `CONFIRMED_VIOLATION`; confirm from any other starting state → `ERR_INVALID_STATE` — `residue.py:87-103`
- §3.9 — insert — ambiguity — record-produced requires `OPEN` (else `ERR_INVALID_STATE`) and may push `produced_record_count` beyond required — `audit.py:62-66`
- §3.9 — revise — mismatch — close rejects any inequality (shortfall *or* excess), not just shortfall — `audit.py:75-77`
- §3.9 — insert — ambiguity — mark-deficient from non-`OPEN` state → `ERR_INVALID_STATE`; no `window_start`/`window_end` ordering enforced; shipments counted only via *included* orders — `audit.py:87-88,21-24`, `core.py:292-297`
- §3.10 — revise — mismatch — `PENDING`/`LAPSED` statuses exist but no endpoint transitions into them (PRD implied inspector administration could) — `acks.py` (no transition route exists)
- §3.10 — insert — ambiguity — per-mill ack list filters (`covers_drug_id`, `status`); no `X-User-ID`-to-mill ownership check on recording — `acks.py:16-19,42-46`
- §3.11 — revise — mismatch — `pending_order_count` counts validated-but-unresolved orders (incremented at validation, decremented at delivery/cancel/return/reject-receipt) — not "sitting in `VALIDATED` and not yet shipped" (shipped orders still count) — `feed_orders.py:197,227`, `shipments.py:57`
- §3.11 — insert — ambiguity — audit-bundle list supports optional `status` filter — `audit.py:50-53`

## Step 7: Test/Fix Iteration — 2026-08-13

**Iteration 1 sweep**: 29/54 failing in all 8 rounds, all with the identical setup error `HTTP 422: ERR_EXTRA_LABEL_USE - intended_use_label does not match drug label indications` — the classic shared-fixture signature (TRIAGE HINT).

**Diagnosis (STEP 2 — test_helpers bug)**: PRD §3.5 states verbatim: "The `intended_use_label` must match the label indications of the VFD's drug; a mismatch is an attempted extra-label use and the submission is rejected with `ERR_EXTRA_LABEL_USE` (HTTP 422)." The drug's only label-indication field per PRD §3.1 is `label_name`. The factory `create_feed_order_payload` defaulted `intended_use_label` to `"label use"` while `create_drug_payload` defaulted `label_name` to `"Test Medication"` — so every fixture-built order violated the PRD's lawful-order precondition and the PRD-faithful implementation correctly rejected submission. The implementation check itself is required by PRD and was not touched.

**Fix**: `test_helpers/fixtures.py::submit_order` — when `intended_use_label` is not explicitly overridden, fetch the VFD's drug and default the label to the drug's `label_name`. This default passes under both plausible readings of "match" (equality or containment). Tests probing `ERR_EXTRA_LABEL_USE` still override the field explicitly.

**Iteration 2 sweep**: 54/54 passed in all 8 parallel rounds. Zero failures. Exit condition met.

No tests deleted. No implementation changes.
