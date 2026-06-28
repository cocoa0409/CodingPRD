# Worklog — task_0653_epoxy_garage_floor_coating

## Step 1: Create Task Directory — 2026-06-26T14:44:44.000Z

Pre-assigned folder `tasks/task_0653_epoxy_garage_floor_coating` with `workspace/` subdir already existed (auto-index skipped per execution parameters). Verified directory and workspace present; no index scan performed.

## Step 2: Generate Scaffold — 2026-06-26T15:20:29.000Z

All three scaffold artifacts are generated and validated. Final lint verdict: **clean**.

Generated the three Expert-difficulty scaffold artifacts for **task_0653_epoxy_garage_floor_coating**, built fresh from the scenario + skill spec (no sibling tasks consulted).

**Archetype:** pricing_engine + workflow_orchestration; entity_topology hybrid; state_machine_shape parallel; role_model peer_roles.

**SCAFFOLD.yaml** (§1.0–§1.7):
- **12 entities**: CoatingSystem, ColorOption, FinancingPlan, Crew, Customer, Project, Assessment, Quote, InstallJob, Warranty, WarrantyClaim, Referral
- **40 endpoints** (incl. `/_clock/set_current_utc` with default 2026-04-01T00:00:00Z). This sits above the 20–32 soft guideline: the count is driven by 7 state machines' mandatory transition endpoints plus mechanically-enforced FK reverse-reachability GETs. Trimmed from an initial 47 by merging PrepScope into Assessment and collapsing claim request-info/approve/reject into one `/claims/{id}/review` action endpoint; remaining endpoints are each load-bearing.
- **23 error codes**
- **6 calculations / 4 variants**: quote_pricing (ESTIMATE vs FINAL) and warranty_proration (PEEL factor 1.00 vs HOT_TIRE 0.50) provide the dual-variant pairs; plus condition_score (weighted+threshold), financing_payment (amortization), cure_window (interval projection), referral_credit_ledger (conserved aggregation)
- **7 state machines**, 2 non-linear on different entities: WarrantyClaim cyclic (SUBMITTED↔NEEDS_INFO revision loop) and Project parallel dimensions (sales_status × build_status); plus branching InstallJob and revert-bearing Warranty
- **2 concurrency_rules** (OCC on Project.version for quote-accept and project-cancel)
- 6 roles (PlatformAdmin/SalesRep/Scheduler/WarrantyAgent opaque; Crew/Customer entity_backed)
- `api_prefix: ""` (flat top-level collections) so FK segment-derivation resolves

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8): 9 rule_ids × 2 = **18 instances**, all 9 Difficulty Rules satisfied with cross-domain differentiation. Second temporal-overlap rule (site cure-window continuous interval vs crew same-day discrete bucket) and second conserved quantity (crew-day occupancy vs referral credit) to satisfy rules 8 and 9. All formula-derived asserts pre-computed as literals (verified by code).

**SCAFFOLD_CORNER_DESIGN.yaml** (§1.9): 7 sections, **31 instances** (29 active + 2 `excluded_because` stubs referencing real §1.8 instances) covering remaining errors, required-field/type/default/computed/system-field claims, RBAC denials, invalid transitions, OCC stale-version negative, pagination envelope, and condition-score tier boundary.

`scaffold_lint.py` final verdict: **clean** — 515 calls scanned, all conform to §1.5; all FKs reverse-reachable; all grounds resolve; all instance names unique.

## Step 3: Copy Shared Files — 2026-06-26T15:20:46.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-26T15:25:57.000Z

All contracts pass. The PRD is complete and verified. Generated `workspace/PRD.md` from the scaffold (Expert difficulty, `epoxy-garage-coating` domain, pricing-engine + workflow-orchestration archetype).

**Document shape:** 280 lines. Sections: §1 Introduction, §2 Global Specifications (10 subsections: RBAC, response structure, pagination, common properties/versioning, logical clock, nested retrieval/reference resolution, monetary precision, validation ordering, OCC, parallel status dimensions), §3 Business Logic (9 subsections), §4 endpoint table, §5 error table.

**Coverage documented:** 13 entities (Project has dual `sales_status`/`build_status`); 41 endpoints (incl. logical clock); 23 error codes (all in narrative + table); 6 calculations in prose (condition_score weighting + prep-tier thresholds, dual-variant quote_pricing with pinned eval order + metallic/seasonal/volume rules, financing amortization with r==0 branch, warranty_proration PEEL=1.00/HOT_TIRE=0.50, cure_window with metallic +24h, referral conserved-credit ledger).

**Hard Contracts — all PASS:** Field coverage 73/73; Rule coverage (21 validations ordered + tie-break + worked example, 2 OCC rejections, all state-machine transitions incl. WarrantyClaim cyclic + Project parallel, 6 calculations, sibling-branch symmetry); Path purity (§3) 346 backtick tokens scanned, 0 path/method tokens. Withheld design YAMLs not opened.

## Step 5: Generate Unit Tests — 2026-06-26T15:38:23.000Z

All complete. Test infrastructure and suite are generated and validated.

**Stage 1 — `test_helpers/`** (9 files): `types.py` (11 entity TypedDicts + status/role enums), `api_client.py` (one method per PRD endpoint), `api_errors.py` (23 error IDs + HTTP map), `assertions.py` (per-entity shape/domain checkers), `factories.py` (input-field-only payload factories), `constants.py` (pricing/score/proration/cure/referral thresholds), `test_users.py` (4 opaque-role shared headers + `make_customer_headers`/`make_crew_headers` per-instance builders for the two entity_backed roles), `fixtures.py` (long lifecycle chain catalog → project → assessment → estimate → send → accept → book → start → complete → mark-cured → claim). All pre-computed cent assertions (827507, 969797, 551671, 275836, 310000, 324375, 150000, 16064) re-derived from PRD §3 formulas before emission.

**Stage 2 — `test_suite/`** (conftest + 6 domain-named test files, **66 tests**): pricing, warranty claims, project lifecycle, install scheduling, referrals/OCC, CRUD/validation/RBAC.

**Translation coverage:**
- **Queue A (Difficulty):** all **18/18** instances translated, each with **≥2 tests**.
- **Queue B (Corner):** all **29/29 non-stub** instances translated (≥1 test each). The **2 `excluded_because:` stubs** correctly NOT translated; both cross-references resolve to real difficulty-design instances.
- **Skips:** none.

**Quality gates passed:** every docstring ends with exactly one `Design:` tag resolving to a real instance; every citation's distinctive substring survives literal grep of PRD.md; no orphan/dual tags; no scaffold/Table N/§1.x leakage; no skip/xfail. All files byte-compile; all 6 modules import; all 66 tests collect under pytest.

## Step 6: Generate Implementation — 2026-06-26T15:38:23.000Z

Implementation complete.

**Stack:** Python 3 + Flask 3.0.3, in-memory dict store (no DB, no disk, no seeding). State wipes on every fresh boot.

**Files created (21)** under `workspace/implementation/`: `start.sh` (foreground, reads `$PORT` default 10000, binds `0.0.0.0`, `exec python3 app.py`), `requirements.txt`, `app.py`. Core: `db.py` (store + logical clock default `2026-04-01T00:00:00Z`, UUID/req-id/referral-code mint, 3-fractional-digit ISO formatter), `errors.py` (23-entry catalog), `response.py` (meta/response_type/data envelope), `middleware.py` (X-User-ID/X-User-Role auth + RBAC). `services/`: `calc.py` (6 calculation rules, Decimal + ROUND_HALF_UP), `common.py`, `serialize.py`, `timeutil.py`. `routes/`: clock, catalogs, customers, projects, quotes, install_jobs, warranties, claims, referrals.

**Endpoints:** all **40** from PRD §4 implemented.

**Highlights:** Dual-variant pricing (ESTIMATE/FINAL) one engine, pinned rounding incl. .5 half-up boundary + metallic 1.20 material multiplier; parallel state dims (sales_status × build_status); 21-level validation priority order incl. install-booking cascade; cure-window scheduling (discrete same-UTC-day crew collision vs continuous half-open `[install_date, vehicle_traffic_ok_at)` interval, touching endpoints do not overlap, metallic +24h); OCC on `expected_project_version` → 412 ERR_STALE_PROJECT_VERSION; warranty proration (PEEL 1.00 / HOT_TIRE 0.50, clamp 0); referral credit ledger (+15000 convert / -15000 clawback) with cascade voiding + crew-day freeing.

**Internal-consistency note (impl-gen self-reported, not a bug):** referral CONVERTED fires only at mark-cured (build→COMPLETE), and COMPLETE is non-cancellable per PRD §3.8, so the clawback path is implemented faithfully and reachable in code though normal API flow cannot land a CONVERTED referral on a cancellable project. Implemented as PRD prose specifies.

## Step 7: Run Tests and Iterate — 2026-06-26T16:10:00.000Z

Clean 8-round parallel sweep achieved: all 8 rounds pass 63/63 (failed=0, errors=0). Orchestrator independently re-verified the final 8-round foreground sweep on a quiet host (load dropped 16→1) after an earlier sweep produced transient server-start ERRORs purely from sibling-pipeline host contention; final authoritative sweep: rounds 1–8 all 63/63.

**Iterations run:** 2 (initial diagnostic sweep + one fix sweep that came back fully clean).

**Initial failure picture:** 4 real assertion failures plus 3 transient server-restart setup failures (infrastructure flakiness under heavy parallel load; did not recur).

**Tests deleted (3) — all STEP 1b UNIQUE-DERIVABILITY failures from an internal PRD contradiction:**
The PRD's cancel cascade describes voiding the warranty / force-closing claims / clawing back a *converted* referral on project cancellation. But a warranty is created and a referral converts *only* at mark-cured, which atomically moves `build_status` `CURING → COMPLETE` (PRD §3.7 line 183, §3.8 line 199). PRD §3.8 line 201 states verbatim that cancel "is permitted only while the build track is at `PRE_BUILD`, `SCHEDULED`, or `CURING`; an attempt to cancel a project whose build track is already terminal at `COMPLETE` or `CANCELLED` is rejected with `ERR_PROJECT_NOT_CANCELLABLE`." So the warranty-void and referral-clawback cascade branches are provably unreachable: a faithful PRD-only implementation rejects the cancel of a `COMPLETE` project (corroborated by the passing `test_cancel_completed_project_not_cancellable`). These three tests each required cancelling a `COMPLETE` (cured) project and asserting cascade success, which no faithful implementation produces.
- `test_cancel_voids_warranty_and_closes_open_claim` (test_03) — unreachable cascade / branch-asymmetric side effect contradicting the cancellability guard. Scaffold rule: `Difficulty/transitive_cascade/cancel_cascades_install_warranty_claim_referral_depth3`.
- `test_cancel_claws_back_converted_referral_credit` (test_03) — same unreachable-cancel contradiction. Scaffold rule: `Difficulty/compensating_invariant/referral_credit_conserved_on_convert_then_clawback`.
- `test_referral_credit_returns_to_baseline_after_clawback` (test_05) — same; convert-then-clawback requires cancelling a COMPLETE project. Scaffold rule: `Difficulty/compensating_invariant/referral_credit_conserved_on_convert_then_clawback`.

(Surviving + passing: `test_cancel_completed_project_not_cancellable`, `test_referral_credit_added_on_conversion`, `test_referral_converts_on_mark_cured_complete` — none cancel a COMPLETE project.)

**Fixes applied to test_helpers/:** None.

**Fixes applied to implementation/ (1):**
- `routes/projects.py`, `decline_project()` — reordered the two decline guards so the `build_status != PRE_BUILD` check (→ `ERR_DECLINE_AFTER_SCHEDULED`) precedes the generic sales-state check (→ `ERR_INVALID_STATE`). PRD §3.5 line 169 verbatim dedicates the scheduled scenario its own error ("once a project has been scheduled, it can no longer be declined, and a late decline is rejected with `ERR_DECLINE_AFTER_SCHEDULED`"); a booked project has `sales_status=ACCEPTED` + `build_status=SCHEDULED`, so the old ordering wrongly returned `ERR_INVALID_STATE`. The DECLINED-re-decline path (still PRE_BUILD) still correctly reaches `ERR_INVALID_STATE`.

The dead-but-PRD-faithful cancel cascade code in `cancel_project()` was left untouched (it traces to PRD §3.8 prose; cardinal rule forbids removing PRD-required implementation checks).

## Step 8: Finalize PRD — 2026-06-26T16:10:56.000Z

The finalized PRD is complete. One edit was applied, pinning the only PRD silence revealed by the Step 7 diff.

**Line counts:** PRD.md = 280 lines; PRD_FINALIZED.md = 280 lines; %-delta = 0% line count, one line revised in place (§3.5, line 169).

**Changes (1 bullet):**
- §3.5 (Declining) — revise — pinned the precedence between the two decline guards: the build-track check is evaluated first (any build state past `PRE_BUILD` → `ERR_DECLINE_AFTER_SCHEDULED` regardless of sales state), and only at `PRE_BUILD` is the sales-state guard applied (non-`LEAD`/`ASSESSED`/`QUOTED` → `ERR_INVALID_STATE`). — `implementation/routes/projects.py:260-265`

**Step 7 diff items addressed:**
1. *Decline guard reorder (the one impl fix):* genuine PRD silence — §3.5 names `ERR_DECLINE_AFTER_SCHEDULED` but never states it takes priority over the generic `ERR_INVALID_STATE` sales-state guard; §2.8's priority list omits `ERR_DECLINE_AFTER_SCHEDULED`. A faithful PRD-only implementer could have checked sales state first. Pinned the impl's ordering. **Edit made.**
2. *The 3 test deletions:* **No edit.** These resolved an internal PRD contradiction (cancel cascade voids warranty / claws back converted referral, but those only exist after mark-cured moves build to `COMPLETE`, and cancel of a `COMPLETE` project is rejected — cascade branches unreachable). Verified `cancel_project()` matches PRD §3.8 exactly incl. unreachable branches. No silence/mismatch to pin.

**Per-edit pre-edit search log:** Edit 1 subject = ordering/precedence of decline endpoint's two guards. Paths enumerated: `routes/projects.py:decline_project()`; grepped all `build_status`/`PRE_BUILD`/`ERR_INVALID_STATE`/`ERR_DECLINE_AFTER_SCHEDULED` across `routes/`+`services/`; confirmed only writers of `build_status` are book_install→SCHEDULED, complete_install→CURING, mark_cured→COMPLETE, cancel_project→CANCELLED, create_project→PRE_BUILD. Wording adjustment: listed post-PRE_BUILD build states as SCHEDULED/INSTALLED/CURING/COMPLETE/CANCELLED to match the broad `!= PRE_BUILD` test; kept general sales clause; made no claim about `ERR_DECLINE_AFTER_SCHEDULED`'s global §2.8 position.

## Step 9: Complete PRD — 2026-06-26T16:15:50.000Z

All edits applied cleanly. PRD_COMPLETED.md produced (terminal signal present on disk).

**Source vs output:** PRD_FINALIZED.md = 280 lines / 47,981 chars; PRD_COMPLETED.md = 280 lines / 49,802 chars; char delta +1,821 (no line-count change — all in-paragraph).

**Counts:** 9 ambiguity-pins, 1 mismatch-revision (10 edits across 9 paragraphs).

**Changes:**
- §2.2 API Response Structure — insert — ambiguity — pinned `api_request_timestamp` to host wall-clock time at response build, not the logical clock — `response.py:13`
- §3.2 Customers — revise — mismatch — PRD claimed email unique among customers; impl never enforces uniqueness → revised to say duplicates accepted without error — `routes/customers.py:15-29`
- §3.2 Referral Program — insert — ambiguity — pinned that explicit `POST /referrals` bumps referred project `version`/`updated_at` while implicit project-create path leaves new project at version 1 — `routes/referrals.py:47-48` vs `routes/projects.py:60`
- §3.5 Accepting — insert — ambiguity — pinned accept returns the accepted quote object, not the project — `routes/quotes.py:100`
- §3.5 Declining — insert — ambiguity — pinned decline returns the updated project object; clarified "non-terminal quote" = DRAFT/SENT — `routes/projects.py:270,280`
- §3.6 Completing the install — insert — ambiguity — pinned complete returns the updated install job — `routes/install_jobs.py:236`
- §3.6 Marking cured — insert — ambiguity — pinned mark-cured returns the updated install job — `routes/install_jobs.py:288`
- §3.7 Coverage window — insert — ambiguity — pinned coverage expiry uses calendar-month addition with day-of-month clamping — `services/calc.py:185-193`
- §3.7 months_elapsed — insert — ambiguity — pinned calendar-based whole-month-floored computation — `services/calc.py:169-182`
- §3.8 Cancellation — insert — ambiguity — pinned cancellable-state check (`ERR_PROJECT_NOT_CANCELLABLE`) evaluated before OCC `expected_project_version` check — `routes/projects.py:296-305`

**Left unchanged (intentional):** §2.8 validation-ordering kept as global abstraction (per-endpoint required/type/enum-vs-reference order varies — `create_assessment` orders state guard before field validation — so a single global clause would mis-state at least one endpoint; bloat/false-claim risk avoided). Action endpoints returning their primary acted-on resource match the natural §2.2 reading; no pins needed.

---

## Pipeline complete — 2026-06-26T16:15:50.000Z

All 9 steps run end-to-end. Final state: **63/63 tests pass across all 8 stability-sweep rounds** (failed=0, errors=0). Terminal signal `workspace/PRD_COMPLETED.md` written (280 lines, 49,802 bytes). Artifacts present: SCAFFOLD.yaml + 2 design YAMLs, PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ + test_suite/ (63 tests, 3 deleted in Step 7), workspace/implementation/ (40 endpoints, Python+Flask, in-memory).
