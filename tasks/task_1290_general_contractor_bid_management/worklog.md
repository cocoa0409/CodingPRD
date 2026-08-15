# Worklog — task_1290_general_contractor_bid_management

RESUME RUN: previous run was terminated after Step 1 only (directory existed with empty workspace/, no worklog). Resuming from Step 2 on 2026-08-12.

## Step 1: Create Task Directory — 2026-08-12T19:23:00.000Z

Created ./tasks/task_1290_general_contractor_bid_management/workspace (done by previous run; verified present and empty).

## Step 2: Generate Scaffold — 2026-08-12T20:25:00.000Z

Scaffold generation complete. All three artifacts are in `/home/ubuntu/github/CodingPRD/tasks/task_1290_general_contractor_bid_management/`, and `scaffold_lint.py` reports: **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (49 endpoints, 12 entities, 18 §1.8 + 40 active §1.9 instances, 624 calls scanned.)

## What was generated

**SCAFFOLD.yaml** (§1.0–§1.7, no difficulty/corner keys):
- **12 entities** — BidPackage, Subcontractor, PrequalApplication, Invitation, Addendum, AddendumAcknowledgment, Bid, BidRevision (append-only, `common_fields: false`), LevelingAdjustment, PostBidInterview, AwardRecommendation, BidderFeedback
- **8 state machines** — including a cyclic revert on BidPackage (`RECOMMENDATION_PENDING → TABULATED` on recommendation return, plus tabulation self-loop), a resubmit cycle on PrequalApplication (`REJECTED → SUBMITTED`), and a reconsider cycle on Invitation (`DECLINED → BIDDING`)
- **4 calculations** — dual-variant prequal score (self-reported vs verified with EMR hard-fail), leveled bid amount (pinned per-adjustment-then-sum rounding), required bid bond (half-up threshold), dual-variant tabulation ranking (apparent-low vs leveled-low)
- **10 ordered validations**, **39 error codes**, **49 endpoints**, **5 roles** (Subcontractor is `entity_backed`; Anonymous only self-registers), **2 OCC concurrency rules** (bid revisions on `Bid.version`, recommendation creation on `BidPackage.version`)
- Complexity profile: compliance/audit + posture-driven gating, flat topology, segregation-of-duties role model (drafter `created_by_user_id` ≠ approver on award decisions)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 18 instances (2 per rule), all with structured, replay-verified `setup_api_calls`. All formula-derived asserts were precomputed (e.g., self-reported 53.50 vs verified 85.00; leveling rounding 107 vs sum-then-round 106; bond boundary 100,000 on base 1,999,999).

**SCAFFOLD_CORNER_DESIGN.yaml** — 48 instances (40 active + 6 `excluded_because` stubs + cross-checks): entities 6, state_machines 11, calculations 8, validations 9, endpoints 3, rbac 5, cross_cutting_layers 5, consistency_model 1. Every error code in §1.6 is triggerable by at least one instance across the two design files.

## Design decisions worth noting
- **Bid creation IS submission** (no DRAFT state) — "bid day" compliance (bond sufficiency, prequal validity, strict `< bid_due_at`) all fires at `POST /bids`, giving clean priority-conflict probes (state-vs-fiscal, safety-vs-temporal).
- **Tabulation is atomic and re-runnable**: eligibility is evaluated in-memory first; zero compliant bids → `ERR_NO_COMPLIANT_BIDS` with no state changes; `DISQUALIFIED` is terminal so re-tabulation never resurrects.
- **Two OCC rules** both reducible to strictly sequential tests; the second exists because recommendation creation pins the package's tabulation version.
- **Addendum acknowledgment uses per-(addendum, subcontractor) rows** addressed via the addendum path (`POST /addendums/{id}/acknowledge`), keeping RBAC ownership checks trivial.
- Endpoint count (49) exceeds the Expert guideline band (20–32) deliberately: the scenario's eight enumerated workflow areas plus 14 FKs each requiring reverse-reachability GETs demand it; difficulty is carried by the coupling (cascades, tabulation, priority conflicts), not CRUD surface.

## Step 3: Copy Shared Files — 2026-08-12T20:27:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1290_general_contractor_bid_management/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-12T20:35:00.000Z

All audits pass. Final summary:

## Generated

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1290_general_contractor_bid_management/workspace/PRD.md` — 301 lines, 6,638 words.

**Section structure** (skeleton designed fresh for the bid-management domain, not copied from the hospital example):
- §1 Introduction — 2 paragraphs, pain-point-first framing, introduces logical clock + immediate-consistency commitments
- §2 Global Specifications (9 subsections): 2.1 RBAC with per-role `identity:` translation (Subcontractor entity-backed; LeadEstimator/ChiefEstimator/PrequalReviewer/Anonymous opaque), 2.2 verbatim fixed envelope block, 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), 2.4 Resource Identity/Versioning (incl. `BidRevision` carrying only `id`/`created_at`, no `updated_at`/`version`), 2.5 Logical Clock & Deadline Discipline, 2.6 Monetary Precision, 2.7 OCC (exactly two endpoints: `expected_bid_version` → `ERR_STALE_VERSION` 412; `expected_bid_package_version` → `ERR_STALE_PACKAGE_VERSION` 412), 2.8 Validation Order (priorities 1–10 explicit), 2.9 Payload Shape Discipline
- §3 Business Logic (10 subsections, chronological bid-event grouping): package setup/invitations, registration/prequal, invitation responses/plan room, prequal scoring (pinned rounding, hard-fail EMR 1.25, references 5B/2B cents, weights 0.40/0.35/0.25), addenda/acknowledgments, bid submission/bonds/revisions (60-minute last-minute rule), leveling (per-adjustment round-half-up before summation; `EXCLUDED_SCOPE` contributes 0 but sets `has_exclusions`), tabulation (sweep order `MISSING_ADDENDUM_ACK` before `PREQUAL_LAPSED`; tie-breaks `submitted_at` then `created_at`), interviews (half-open overlap, adjacency allowed) + recommendation pipeline (SoD), award cascade + feedback snapshots
- §4 Endpoint table — 49 endpoints, 4 columns only
- §5 Error catalogue — 39 errors, 2 columns only

**Coverage-audit results:**
- Contract 1 (field names): 80 required (66 entity fields + endpoint input/query/output identifiers incl. `to_iso8601`, `current_utc`, `intent`, `decision`, `reason`, `note`, `new_base_bid_cents`, both OCC tokens, `has_exclusions`, `pending_addendum_ack_count`, `is_compliant`), 80 present, 0 missing — **PASS** (after repairing 2 gaps: `addendum_id`, `current_utc`)
- Contract 2 (rule coverage): all 7 state machines' transitions with preconditions paired to error IDs and side effects expressed (incl. cascades: decline→ack waive, reconsider→ack re-create, addendum issuance fan-out, tabulation two-phase sweep+ranking, award cascade with feedback snapshots); both OCC rules with endpoint+field+error+status; both `prequal_score` variants with hard-fail rule and pinned rounding order; `leveled_bid_amount`, `required_bid_bond` (equality passes, one cent short fails); `bid_tabulation_ranking` (both variants, tie-breaks, empty-set failure with no state changes); all 10 validation priorities sequenced in §2.8; all 39 error IDs appear in §2/§3 prose — **PASS**
- Contract 3 (§3 path purity): 359 backtick tokens scanned, 0 path tokens, 0 bare HTTP methods, 0 method+path combos — **PASS**
- All 27 state/enum strings (incl. `GC_ALLOWANCE`/`SUB_QUOTE`/`EXCLUDED_SCOPE`, `MISSING_ADDENDUM_ACK`/`PREQUAL_LAPSED`) present verbatim.

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-12T21:10:00.000Z

All done. Final verification: **76/76 tests pass** under `prd-bench-local-run --isolation per-test-server` against the workspace implementation.

## Summary

### Generated infrastructure — `/home/ubuntu/github/CodingPRD/tasks/task_1290_general_contractor_bid_management/test_helpers/`
| File | Contents |
|---|---|
| `types.py` | 12 status/role enums + 12 entity TypedDicts (`BidRevision` correctly carries only `id`/`created_at` — no `updated_at`/`version`) |
| `api_client.py` | `ApiClient(GenericApiClient)` with one method per PRD endpoint (52 methods, incl. PATCH/DELETE leveling, clock) |
| `api_errors.py` | All 39 `ApiErrorId` members + HTTP status map, registered via `set_error_http_status_map` |
| `assertions.py` | 12 `assert_<entity>()` validators + `assert_timestamp_equals` (instant-level comparison, robust to `.000Z` vs `Z` serialization — confirmed necessary by the live server) |
| `factories.py` | 17 payload factories, input fields only |
| `constants.py` | Score weights/refs, EMR floor/ceiling/hard-fail, 70 threshold, 365-day window, 60-minute window, default clock/dates |
| `test_users.py` | 5 role headers + per-instance builders; canonical `le-100`/`ce-900` drafter/decider pair; `make_subcontractor_headers(entity_id)` for the entity-backed role |
| `fixtures.py` | Tiered composites: registration → prequal approval → invite/respond → publish → bids → close → tabulate → draft/submit recommendation → full award cascade |
| `__init__.py` | Barrel export |

### Test suite — `test_suite/` (conftest + 6 files, 76 tests)
- **Queue A (Difficulty): 36 tests — all 18/18 instances covered ×2.** dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant.
- **Queue B (Corner): 40 tests — all 40 non-stub instances covered ×1.** entities 6, state_machines 10, calculations 4, validations 9, endpoints 3, rbac 5, cross_cutting_layers 3.
- **8 `excluded_because:` stubs not translated**; all 8 cross-references verified to resolve to real difficulty instances.
- **Instances skipped for PRD-coverage failure: 0** — every non-stub instance passed the two-condition filter (PRD §2.8 explicitly pins the validation cascade order, which legitimized all priority-pair instances).

### Stage 2 audit results
- Tag audit: 0 failures, 0 orphans, 0 dual-tags; every `Design:` line is the docstring's last line and resolves verbatim to a yaml `name:`.
- Citation audit: 145 quoted fragments, **all verbatim** against PRD.md (normalized-whitespace grep; six quotes initially missed the PRD's literal `**` bold markers and were corrected).
- Hygiene: no `skip`/`skipif`/`xfail`, no scaffold references, no unused imports, all modules compile and import.

### Adjustments made after the live run (3 failures triaged)
1. **Test bug** — stale invitation object asserted pre-response state; fixed by capturing the `respond` return value.
2. **Over-strong assertion dropped** — `resolved_amount_cents == 0` on an `EXCLUDED_SCOPE` adjustment. PRD §3.7 says such adjustments "contribute 0 to the leveled total regardless of its price fields" but pins `resolved_amount_cents` to "that figure verbatim" when `amount_cents` is given — the stored field is not uniquely derived. Kept the derivable assertions (leveled total 107, `has_exclusions` true).
3. **Precedence relaxed per the error-precedence silence pattern** — leveling write after award: every bid of an AWARDED package is necessarily terminal, so the call violates both `ERR_LEVELING_LOCKED` and `ERR_BID_INVALID_STATE`, both at cascade priority 5 with no PRD-stated intra-tier order. Assertion uses `validate_error_is_one_of([ERR_LEVELING_LOCKED, ERR_BID_INVALID_STATE])` + explicit 409, with both PRD sentences cited.

### Runner note
`prd-bench-local-run --isolation per-test-server` requires the start command in `cd <abs-dir> && bash start.sh` form — the pytest plugin's per-test restart parses that prefix; a bare `bash path/start.sh` resolves against the pytest rootdir and every test errors after the first restart.

## Step 6: Generate Implementation — 2026-08-12T21:10:00.000Z

Done. The implementation is complete and verified end-to-end.

## Summary

### File inventory
All under `/home/ubuntu/github/CodingPRD/tasks/task_1290_general_contractor_bid_management/workspace/implementation/`:

- `start.sh` — executable launcher; guarded `pip install` (no-op when flask present), then `exec python3 app.py`
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask app factory, blueprint registration, `ApiError`/404/405/500 handlers, binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — empty-on-boot in-memory store, `LogicalClock` (starts exactly `2026-08-01T00:00:00Z`, forward-only), UUID ids, 3-fractional-digit ISO 8601 timestamps, `stamp_new`/`touch` (version starts at 1, +1 per mutation; `BidRevision` exempt from `updated_at`/`version`)
- `errors.py` — full error catalog with exact scaffold error_ids and HTTP statuses (incl. 402 `ERR_BID_BOND_INSUFFICIENT`, 412 OCC errors)
- `response.py` — envelope: `{meta:{api_request_id, api_request_timestamp}, response_type, data}`; list responses add `limit`/`offset`/`total_count`/`has_more` to `meta`
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, role gating, payload-shape discipline (unknown/read-only field rejection, exactly-one-of, ranges), `limit`/`offset` parsing (default 10, min 1, max 100)
- `services/prequal.py` — prequal score (components rounded 2dp half-up before weighting; verified-variant EMR hard fail ≥1.25 → 0.00), lazy `APPROVED→EXPIRED`, `current_prequal_status` precedence walk
- `services/bids.py` — required bid bond (half-up integer cents), per-adjustment rounding before summation, leveled amount, pending-ack counting, `addendum_ack_complete` recompute, tabulation (compliance sweep then ranking)
- `routes/` — 11 modules: `clock`, `bid_packages`, `subcontractors`, `prequal`, `invitations`, `addendums`, `bids`, `leveling`, `interviews`, `recommendations`, `feedbacks`

### Endpoint coverage
**49/49 endpoints** from the scaffold §1.5 table are implemented (counted via AST over route decorators; matches the table exactly).

### State machines implemented
- **BidPackage**: DRAFT→PUBLISHED→BIDDING_CLOSED→TABULATED→RECOMMENDATION_PENDING→AWARDED, plus TABULATED→TABULATED re-tabulation and RECOMMENDATION_PENDING→TABULATED on RETURN; leveling lock/unlock tied to package state
- **PrequalApplication**: SUBMITTED→APPROVED/REJECTED, REJECTED→SUBMITTED resubmit, lazy APPROVED→EXPIRED on read/consult
- **Invitation**: SENT→BIDDING/DECLINED, BIDDING→DECLINED (ack-waive cascade), DECLINED→BIDDING reconsider (PENDING ack re-creation, WAIVED retained)
- **AddendumAcknowledgment**: PENDING→ACKNOWLEDGED/WAIVED (incl. system waive on decline)
- **Bid**: create-is-submit, revise (OCC via `expected_bid_version`), withdraw, DISQUALIFIED at tabulation, AWARDED/NOT_AWARDED cascade
- **PostBidInterview**: SCHEDULED→HELD with half-open room-overlap rejection
- **AwardRecommendation**: DRAFT→SUBMITTED→APPROVED/RETURNED with SoD (`ERR_SOD_VIOLATION`, 403) and package OCC (`expected_bid_package_version`)
- **BidderFeedback**: DRAFT→SENT; DRAFT invisible to Subcontractor

### Calculations implemented
- `prequal_score` (both variants; pinned component-rounding-then-weighting; EMR piecewise with floor 0.70/ceiling 1.20; hard fail 1.25)
- `leveled_bid_amount` (per-adjustment round-half-up before sum; EXCLUDED_SCOPE contributes 0 but sets `has_exclusions`)
- `required_bid_bond` (half-up integer cents; equality passes)
- `bid_tabulation_ranking` (apparent by base, leveled by leveled; ties by `submitted_at` then `created_at`; `leveled_rank` snapshotted onto feedback at award; empty compliant set → `ERR_NO_COMPLIANT_BIDS` with zero state changes)

### Boot confirmation
`start.sh` runs the server **in the foreground via `exec`**, bound to `0.0.0.0:$PORT`. Verified with a double-boot harness (`/tmp/reboot_check.py`): boot 1 created a package (total_count=1), process killed, boot 2 on the same port came up clean with total_count=0 — confirming per-test-server isolation works with no carry-over state and no startup seeding. Two live test suites (full lifecycle + corner cases: hard-fail EMR, lazy expiry, disqualification ordering, decline/reconsider cascades, re-tabulation, award feedback ranks, OCC 412s, SoD 403, leveling lock 409, half-up rounding) all pass.

## Step 7: 8-Round Stability Sweep & Diagnostic Loop — 2026-08-12T21:40:00.000Z

Ran the 8-parallel-round stability sweep (`prd-bench-local-run --isolation per-test-server`, 76 tests/round) until a fully clean sweep.

- **Sweep 1**: 6 failures, all `status: error` in *setup* — "API server could not be restarted" (runner's hardcoded 15s readiness poll expired). Zero assertion failures: every test that actually executed passed. Failures clustered in a single ~8s wall-clock window and hit different tests per round (`test_return_swings_package_back_to_tabulated` ×2, `test_time_range_validation_and_double_complete` ×2, `test_approval_cascades_package_and_bids`, `test_overlapping_same_room_interview_rejected`).
- **Diagnosis**: host CPU saturation. ~30 sibling `prd-bench-entrance` pipelines share this host; load average 32–49 on 32 cores, `%idle` ≈ 3%. Server cold boot is ~0.5s CPU / ~1.1–1.7s wall under load, but during runqueue storms a spawned server starves past the 15s poll window. Not a test bug, not an implementation bug — no test deletion or assertion change was warranted (diagnostic protocol STEPs 1–3 never triggered: there was no failing *test*, only failing *server spawns*).
- **Fix applied** (`workspace/implementation/start.sh` only): collapsed the two-interpreter boot (`python3 -c "import flask"` guard + `exec python3 app.py`) into a single `python3 -c` that checks flask via `importlib.util.find_spec` (no module execution) and `os.execv`s into `app.py`. Saves ~0.3–0.4s of every per-test reboot (~30%), shrinking the stall-vulnerability window. Boot verified manually.
- **Sweep 2**: 4 setup-phase restart timeouts, again clustered in one ~9s window (21:35:40–49); all assertions green otherwise.
- **Sweep 3**: **76/76 × all 8 rounds — clean.** Exit criterion met.

No changes to `test_suite/`, `test_helpers/`, or implementation logic (routes/services/db/errors/middleware/response untouched). No tests deleted, no assertions weakened, no PRD-required check modified.

## Step 8: Finalize PRD — 2026-08-12T21:50:00.000Z

Done. PRD_FINALIZED.md is a byte-identical copy of PRD.md (verified with `cmp`).

## Conclusion: no PRD edits warranted

The entire `<step_7_diff>` contains zero behavior-revealing items:

- **Tests deleted**: None. **test_helpers/ fixes**: None. **test_suite/ fixes**: None.
- **Implementation fixes**: One file, `workspace/implementation/start.sh` — a launcher-only boot-performance change (collapsed two-interpreter boot into a single `python3 -c` using `importlib.util.find_spec` + `os.execv`), explicitly with zero API-behavioral impact.
- All sweep failures were setup-phase server-restart timeouts caused by host CPU saturation (~30 sibling pipelines, load avg 32–49 on 32 cores), not test or implementation defects; every executed assertion passed, and Sweep 3 was 76/76 × 8 rounds clean.

**Verification of the diff's claims** (before deciding on a null patch):
- File mtimes confirm only `start.sh` (21:32) changed after the original implementation was written (20:35–20:43); all routes/services/db/errors/middleware/response/app.py files are untouched. The 21:24 directory mtimes on `routes/`/`services/` are from `__pycache__` creation during sweep runs.
- Read `start.sh`: it still `exec`s into the same `app.py` on the same interpreter; only the flask-presence check mechanism changed (`find_spec` vs `import flask`).
- Read `app.py`: standard Flask entrypoint, `host="0.0.0.0"`, `PORT` env (default 10000) — unchanged and consistent with the PRD's API contract.

Since the sole fix concerns process-boot mechanics invisible to the API surface — a topic PRD.md does not (and need not) specify — there is no PRD silence or PRD/impl mismatch to pin. Per the task's explicit note, the correct output is a byte-identical copy rather than invented edits.

## Summary

- **Line counts**: PRD.md = 301 lines; PRD_FINALIZED.md = 301 lines; **0% delta** (byte-identical, `cmp` clean).
- **Changes**: None.
- **Per-edit pre-edit search log**: Not applicable — zero edits were made. The pre-commit investigation above (subject: server boot/launch behavior; paths enumerated: `implementation/start.sh`, `implementation/app.py`, plus mtime audit of all `implementation/**/*.py`) confirmed no edit subject exists, so no wording had to be validated against any code path.

**Output file**: `/home/ubuntu/github/CodingPRD/tasks/task_1290_general_contractor_bid_management/workspace/PRD_FINALIZED.md`

## Step 9: Complete PRD — 2026-08-12T22:05:00.000Z

Done. `PRD_COMPLETED.md` is produced at `/home/ubuntu/github/CodingPRD/tasks/task_1290_general_contractor_bid_management/workspace/PRD_COMPLETED.md` as a minimal patch over `PRD_FINALIZED.md` (which existed and was used as the source).

**Counts**
- Source: `PRD_FINALIZED.md` — 301 lines / 48,812 chars. `PRD_COMPLETED.md` — 301 lines / 51,620 chars. Char delta: **+2,808** (all edits are in-paragraph; no sections or lines added/removed; 13 physical lines touched).
- **Ambiguity-pins: 11. Mismatch-revisions: 4.**

**Changes (one bullet each)**
- §2.1 — revise — mismatch — "estimator roles may read any resource" qualified by the §4 role lists, excluding `PrequalReviewer` from leveling-sheet, leveling-adjustment, and bidder-feedback endpoints — implementation/routes/bids.py:270, 298, 346.
- §2.3 — insert — ambiguity — list ordering tie-break by `id` ascending for equal `created_at`; `has_more` defined as `offset + len(page) < total_count` — implementation/response.py:27, implementation/routes/bid_packages.py:91 (same sort pattern in every list route).
- §2.7 — insert — ambiguity — OCC version comparison is evaluated last, after every other §2.8 gate, immediately before the mutation — implementation/routes/bids.py:206-207 (after deadline+bond), implementation/routes/recommendations.py:76-77 (after active-recommendation check).
- §2.8 — revise — mismatch — prequalification gate (`ERR_PREQUAL_NOT_APPROVED`) moved from priority 6 to priority 7: impl checks invitation-`BIDDING` and duplicate-bid *before* prequal on bid creation, matching §3.6's enumeration — implementation/routes/bids.py:88-98.
- §2.8 — revise — mismatch — payload-shape timing rewritten to impl's actual pattern: path-identifier existence confirmed before the body is inspected; creation endpoints run unknown-field/missing-field checks before FK existence; per-field type/range/enum/exactly-one-of checks fire as consumed — implementation/routes/bids.py:178-186 vs 71-81, implementation/routes/prequal.py:208-222, implementation/routes/leveling.py:98-108.
- §3.2 — insert — ambiguity — verified inputs carry the same ranges as declared counterparts (revenue/bonding int ≥ 0, EMR > 0); a partially supplied verified set on a rejection is discarded entirely — implementation/routes/prequal.py:155-197.
- §3.5 — insert — ambiguity — on acknowledge and waive, the package-state gate (`ERR_PACKAGE_INVALID_STATE`) is evaluated before the PENDING-acknowledgment lookup (`ERR_ACKNOWLEDGMENT_NOT_FOUND`) — implementation/routes/addendums.py:156-164, 186-195.
- §3.6 — insert — ambiguity — a successful revision responds 200 with the updated bid object, not the new revision row — implementation/routes/bids.py:228.
- §3.7 — insert — ambiguity — leveling-sheet `is_compliant` defined: bid `SUBMITTED`, zero pending acks, currently approved prequal (lazy expiry applied) — implementation/routes/bids.py:278-282.
- §3.7 — insert — ambiguity — the bid `SUBMITTED` check (`ERR_BID_INVALID_STATE`) is evaluated before the package leveling-lock check (`ERR_LEVELING_LOCKED`) — implementation/routes/leveling.py:41-47.
- §3.7 — insert — ambiguity — adjustment edit is partial; a price field supplied as explicit null is cleared and the exactly-one-of rule is re-validated against the resulting pair — implementation/routes/leveling.py:110-125.
- §3.8 — insert — ambiguity — each tabulation disqualification decrements the package's `submitted_bid_count` by 1 — implementation/services/bids.py:122.
- §3.9 — insert — ambiguity — `outcome_notes` is a required field of the interview-complete call — implementation/routes/interviews.py:91.
- §3.10 — revise — mismatch — feedback visibility pinned to `LeadEstimator` and `ChiefEstimator` (not "estimator roles" broadly; `PrequalReviewer` gets `ERR_FORBIDDEN_ROLE`) — implementation/routes/bids.py:346.
- §4 preamble — insert — ambiguity — enumerated the optional equality filters per list endpoint (`/bid-packages`: status/apparent_low_bid_id/leveled_low_bid_id; `/prequal-applications`: subcontractor_id/status; `/invitations`: bid_package_id/subcontractor_id/status; `/addendums`: bid_package_id; both acknowledgment listings; `/bids`: bid_package_id/subcontractor_id/status) — list handlers in implementation/routes/*.py.

Notable finding: the only genuine PRD-vs-impl contradictions were in §2.8 (priority-6/7 placement of the prequal gate; the "schema-parse fires immediately after priority 1–2" claim) and the two loose "estimator roles" phrasings (§2.1, §3.10) that the §4 table and impl narrow. Everything else in the PRD — state machines, scoring formula and rounding order, bond math, tabulation tie-breaks, cascades, error catalog — matched the implementation as written.
