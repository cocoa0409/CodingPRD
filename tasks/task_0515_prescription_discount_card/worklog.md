# Worklog — task_0515_prescription_discount_card

Scenario: Prescription Discount Card & Price Comparison (GoodRx style): drug/dosage search & pharmacy price compare, coupon (BIN-PCN-Group) generation, discount-vs-insurance choice, pharmacy adjudication & savings calc, gold-membership tier, mail-order option, telehealth referral, manufacturer copay-card linkage

Difficulty: Expert (§0.4 Expert tier — 10-15 entities)

## Step 1: Create task directory — 2026-06-26T19:35:53.000Z

Created `tasks/task_0515_prescription_discount_card/workspace/` (task dir pre-allocated per orchestrator args). Verified INSTRUCTION.md and all prd-bench skills present.

## Step 2: Generate scaffold (Expert tier) — 2026-06-26T19:57:43.000Z

Generated a complete three-file scaffold for **task_0515_prescription_discount_card** (GoodRx-style prescription discount card & price comparison), designed at the **Expert** difficulty tier per §0.4.

**Files written** (all in `tasks/task_0515_prescription_discount_card/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (no design keys) — 1779 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design` — 1155 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design` — 1982 lines

**Expert-tier dimensions:**
- **13 entities** (Drug, Pharmacy, PriceQuote, Member, GoldMembership, DiscountCard, PriceComparison, InsuranceEstimate, Claim, CopayCard, CopayLink, MailOrderFulfillment, TelehealthReferral) — within the 10–15 band.
- **59 endpoints**, **21 error codes**, **8 calculations** (with 3+ dual-variant/multi-mode), **9 state machines** including parallel dimensions (GoldMembership billing×access), branching-with-revert + cycle (Claim), and cascades.
- Primary archetype: Pricing engine; secondary: Compliance/audit. Layers: dual-variant calc, OCC, selector policy, derived-field reconciliation. Topology: flat; role model: peer roles.

**Design-file instance counts:**
- §1.8 (depth): **18 instances** — exactly 2 per each of the 9 Difficulty Rules.
- §1.9 (breadth): **46 active instances + 4 `excluded_because` stubs = 50 total**, walking the claim-extraction-guide sections.

**Verification performed:** `scaffold_lint.py` → `VERDICT: clean lint` (59 endpoints, 13 entities, 18+46 instances, 494 calls; all checks a–f pass). All three files parse as YAML; all `grounds` references resolve; all 21 errors triggered; instance names unique across both files; no forbidden concurrency vocabulary; all 4 stub references resolve; formula-derived assert literals independently confirmed.

One notable fix: `api_prefix` set to `""` (flat top-level resources) for linter FK reverse-reachability; two computed denormalized pointer fields (`Member.active_gold_membership_id`, `PriceComparison.selected_pharmacy_id`) reworded off the canonical `FK ->` prefix since they are selection results, not ownership FKs.

## Step 3: Copy INSTRUCTION.md — 2026-06-26T19:57:49.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-26T20:03:41.000Z

Generated the PRD at `workspace/PRD.md` — **280 lines**.

**Major sections covered:**
- **§1 Introduction** — pricing engine with compliance/audit layer.
- **§2 Global Specifications** — 11 subsections (2.1–2.10): RBAC (five roles, entity-backed `Member` vs four opaque operators), verbatim §2.2 response envelope, pagination, resource identity/timestamps/versioning (`InsuranceEstimate` exempt from `updated_at`/`version`), integer-cents precision, OCC on claim reversal, validation priority ordering, FK reachability/filtered reads, logical clock (`2026-05-01T00:00:00Z` default), cascade/reconciliation semantics.
- **§3 Business Logic** — 12 subsections by entity lifecycle: catalogue, price quotes, best-price selector, discount-vs-insurance, parallel-dimension Gold membership, discount-card minting, claim adjudication/savings, copay cards/linkage waterfall offset, reversal/re-adjudication, mail order, telehealth, controlled-substance safeguards. Constants (999/1999 cents, 86,400 s, BIN `610279`, PCN/Group codes) embedded.
- **§4 Endpoint Definitions** — 4-column table covering all 61 endpoints + 201/200 status-code rule.
- **§5 Error Code Catalogue** — 2-column table for all 21 error codes.

**Hard Contracts (verified):** Contract 1 (Field-Name Coverage) 59/59 entities + 42/42 endpoint inputs PASS; Contract 2 (Rule Coverage) all transitions/calcs/validations/OCC/cascades PASS; Contract 3 (§3 Path Purity) 0 slash-paths/bare-methods PASS. Confirmed: did NOT read either withheld design file.

## Step 5: Generate unit tests — 2026-06-26T20:17:52.000Z

Generated test infrastructure strictly from the two design indices.

**test_helpers/ (9 files):** `types.py` (13 entity TypedDicts + 14 status/role enums; `InsuranceEstimate` carries only `id`/`created_at`), `api_errors.py` (21 error IDs + HTTP map), `api_client.py` (one method per endpoint, all 57 incl. clock), `constants.py`, `factories.py`, `assertions.py`, `test_users.py` (opaque-role constants + `make_member_headers` builder for entity_backed Member), `fixtures.py` (composite backbone with identity threading), `__init__.py`.

**test_suite/ (conftest + 4 files):** `test_01_pricing_and_calculations.py` (17), `test_02_state_machines_and_cascades.py` (17), `test_03_dependencies_overlap_and_invariants.py` (18), `test_04_crud_validation_and_access.py` (29). **81 test functions total**, each with exactly one `Design:` tag.

**Coverage vs design indices:** Queue A (Difficulty) **18/18 instances translated, ≥2 tests each** (34 tests), none skipped. Queue B (Corner) **45/46 non-stub instances translated**, **1 skipped**: `entities/system_fields_generated_on_member_create` (asserts `Member.version == 1`, but PRD §2.4 never names the initial version value — not uniquely derivable). All 4 `excluded_because:` stubs verified to resolve; none translated (correct).

**Verification:** all modules compile; all 121 PRD-citation fragments match PRD.md verbatim; no scaffold leakage; no skip/xfail markers; no dual-tagged/untagged tests; identity threading confirmed (ownership-gated calls use `make_member_headers`).

⚠️ Flagged: skipped `version==1` instance reflects genuine PRD under-specification (initial version value never stated).

## Step 6: Generate implementation — 2026-06-26T20:17:52.000Z

Generated Python + Flask implementation at `workspace/implementation/`.

**Stack:** Python 3 + Flask 3.0.3 (only dependency). Blueprint-per-resource routing; business logic in `services/` layer.

**Files:** `start.sh` (guarded pip install, `exec python3 app.py`), `requirements.txt`, `app.py`, `db.py` (in-memory store + logical clock + audit/id helpers), `response.py` (exact envelope), `errors.py` (21 IDs), `middleware.py` (X-User-ID/X-User-Role auth, 5 roles, ownership), `common.py` (body parsing, pagination, FK existence), `services/` (`calculations.py`, `claim_engine.py`, `serializers.py`), `routes/` (14 modules, all 50+ endpoints across 13 entities).

**State:** in-memory only — module-level dicts in `db.py` keyed by UUID. No SQLite/file/tmp. Fresh boot = empty store, clock at `2026-05-01T00:00:00Z`. No seeded/preloaded data (verified all 13 tables hold 0 records on fresh boot).

**start.sh contract confirmed:** reads `$PORT`, binds `0.0.0.0`, runs foreground via `exec`, responded within 2s.

**Smoke verification:** best-price selection (standard vs Gold), insurance recommendation incl. TIE_DISCOUNT, deterministic BIN/PCN/group/member-code, claim adjudication w/ three-cap copay waterfall, reversal w/ OCC (412/200/409) + compensation cascade, lifetime-savings reconciliation, parallel Gold state machine w/ lapse-voids-GOLD-cards cascade, controlled-substance geo-blocking, mail-order pipeline, RBAC (401/403), ownership, not-found ordering, pagination bounds.

⚠️ Note: a couple PRD-unpinned edges (publish quote against non-ACTIVE pharmacy; adjudicate/mail-order with no resolvable active quote) mapped to generic `ERR_VALIDATION` (422) since no dedicated error ID exists.

## Step 7: Run tests and iterate to PASS — 2026-06-26T20:30:25.000Z

Final state verified: all 8 rounds 81/81 passing.

**Iterations run:** 3 sweeps (initial diagnostic + 2 fix-and-verify sweeps), followed by 1 confirmation sweep. Final state: two consecutive fully-clean 8-round parallel sweeps (16 rounds, all 81/81 passing, zero failures, zero errors).

**Tests deleted:** None. Both failing tests asserted PRD-verbatim, uniquely-derivable rules.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `create_active_gold_member`: now captures the return value of `record_gold_payment` so the returned `gm` reflects the post-payment state (`billing_status="PAID"`, `access_status="ACTIVE"`). Previously it returned the stale pre-payment object (`PENDING_PAYMENT`), causing `test_voluntary_revoke_leaves_billing_paid`'s precondition assert `gm["billing_status"] == "PAID"` (line 41) to fail. This was a STEP-2 test-helper bug: the implementation's record-payment/revoke logic was already PRD-correct (record-payment → PAID, voluntary revoke leaves billing unchanged); the fixture just handed the test a stale snapshot. Other callers only use `gm["id"]` (unchanged), so the fix is safe.

**Fixes applied to `implementation/`:**
- `implementation/app.py` (module top) — added a self-contained `socket.getfqdn` patch for unspecified bind addresses (`0.0.0.0` etc.) that returns `"localhost"` instead of paying a ~5s reverse-DNS (PTR) stall during Werkzeug's `server_bind`. Without it, each per-test reboot cost ~7s, which under the 8× concurrent sweep pushed restarts past the runner's 15s restart-poll window and surfaced as spurious "API server could not be restarted" setup errors. Boot dropped from ~7s to ~0.25s. (Cosmetic-only patch; does not alter binding or any response.)
- `implementation/app.py` (`__main__` block) — wrapped `app.run(...)` in a bounded bind-retry loop (40 × 0.25s) that catches `OSError`. Under per-test-server isolation the runner SIGKILLs the prior server and immediately respawns on the same port; the kernel can briefly hold the port, making a single `bind()` raise EADDRINUSE and exit instantly (reported as "could not be restarted" / "Connection reset by peer"). The retry rides out the transient port hand-off. This eliminated the residual restart-race flakiness that remained after the getfqdn fix.

All storage remains in-memory only (module-level dicts in `db.py`); no seeding, no persistence — start.sh re-invocation wipes all state.

## Step 8: Finalize PRD — 2026-06-26T20:32:15.000Z

`PRD_FINALIZED.md` is a **byte-identical copy of `PRD.md`** (zero edits) — confirmed correct outcome.

**Line counts / delta:** PRD.md = 280 lines, PRD_FINALIZED.md = 280 lines, **0% delta** (matching SHA-1 `ffd69e49…`).

**Why zero edits** — all three `<step_7_diff>` items are infrastructure/fixture in nature; none reveals a PRD silence or PRD/impl mismatch in observable API behavior:
1. `test_helpers/fixtures.py` stale-snapshot fix → impl `routes/gold_memberships.py` `record_payment`/`revoke_membership` already match PRD §3.5 verbatim (record-payment → PAID; voluntary revoke leaves billing_status unchanged). Pure fixture bug, no PRD ambiguity.
2. `app.py` `socket.getfqdn` patch → cosmetic startup-log only; not PRD-observable.
3. `app.py` `__main__` bind-retry loop → boot/port-binding infrastructure; not PRD-observable.

## Step 9: Complete PRD — 2026-06-27T05:50:09.000Z

All edits are in place and verified. The scan is complete and PRD_COMPLETED.md now pins every implementation behavior.

## Summary

**Source vs. completed:**
- `PRD_FINALIZED.md`: 280 lines, 44,827 bytes (44,737 chars excl. trailing) → `PRD_COMPLETED.md`: 280 lines, 46,085 bytes. **Char-delta: +1,252.** Line count unchanged (all edits in-paragraph; no new sections/paragraphs).

**Counts:** ambiguity-pins: **7**, mismatch-revisions: **2** (9 total).

**Changes:**
- §2.3 Pagination — insert — ambiguity — pinned `id` ascending as the tie-breaker when records share `created_at` — `common.py:57`
- §2.4 Resource Identity/Versioning — insert — ambiguity — pinned `version` initial value as 1 — `db.py:90`
- §2.7 Validation Ordering — revise — mismatch — `ERR_INVALID_REQUEST` is not "last-resort"; impl runs field-presence/type/enum + numeric-bound checks right after auth/role and before ownership/existence/state/OCC/business — `comparisons.py:107-119`, `price_quotes.py:39-45`, `members.py:16-23`
- §3.1 Catalogue (Drugs) — revise — mismatch — `ndc` uniqueness is not enforced; duplicates accepted (PRD claimed uniqueness, impl has no such check) — `drugs.py:16-41`
- §3.2 Publishing Quotes — insert — ambiguity — publishing against a non-`ACTIVE` pharmacy is rejected with `ERR_VALIDATION` — `price_quotes.py:48-49`
- §3.3 Members (registration) — insert — ambiguity — duplicate `email` registration is rejected with `ERR_VALIDATION` — `members.py:24-26`
- §3.3 Best-Price Selector — insert — ambiguity — final tie-break is the lexicographically smaller quote `id` (after effective price, dispense fee, `created_at`) — `calculations.py:67-72`
- §3.7 Claim Adjudication — insert — ambiguity — quote resolution adds `id` tie-break after `created_at`, and no resolvable `PUBLISHED` quote yields `ERR_VALIDATION` — `calculations.py:97-102`, `claim_engine.py:30-32`
- §3.10 Mail Order — insert — ambiguity — quote resolution adds `id` tie-break, no resolvable quote yields `ERR_VALIDATION`, and shipping a non-`ACTIVE` pharmacy yields `ERR_INVALID_STATE` — `calculations.py:97-102`, `mail_orders.py:54-55`, `mail_orders.py:107-108`

All other implementation behaviors (envelope shapes, audit-field set, immutable `InsuranceEstimate`, OCC reversal, role/RBAC including public-endpoint exemption, the two parallel Gold dimensions and their cascades, copay waterfall + transitive exhaustion/restore, lifetime-savings reconciliation, controlled-substance geo-gating, coupon credential derivation, coverage-window buffer, the `610279`/`GDX`/`STD`/`GOLDRX`/`DISCRX` constants and `999`/`1999`/`86400` values) were already uniquely pinned by the PRD and required no change.
