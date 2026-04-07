import {
    apiClient,
    buildUserHeaders,
    handleApiResponse,
    validateErrorEnvelope,
    createReviewAssignmentPayload,
    createReviewInvitationPayload,
    Journal,
    ReviewAssignment,
    Review,
    Manuscript, ManuscriptStatus,
    ReviewStatus,
    UserRole,
    ApiErrorId,
    ConflictOfInterestType,
    setupJournal, setupManuscript,
    setupReviewerProfile
} from '../../../test-helpers';

describe('Phase 5: Advanced Edge Cases and Validation Ordering', () => {
    const journalEditorHeaders = buildUserHeaders('jour-editor-1', UserRole.JournalEditor);
    const sectionEditorHeaders = buildUserHeaders('sect-editor-1', UserRole.SectionEditor);
    const managingEditorHeaders = buildUserHeaders('mng-editor-1', UserRole.ManagingEditor);

    describe('Validation Order Tests', () => {
        it('should return ERR_EXPERTISE_MISMATCH when both expertise and concurrency limit are violated', async () => {
            const journal = await setupJournal();
            const manuscript = await setupManuscript(journal.id);
            const reviewer = await setupReviewerProfile(journal.id, { expertise_areas: ['Medieval History'] });

            const otherManuscripts: Manuscript[] = [];
            for (let i = 0; i < 5; i++) {
                const ms = await setupManuscript(journal.id);
                otherManuscripts.push(ms);
            }

            const inReviewJournal = await apiClient.beginReview(journal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));

            for (let i = 0; i < 5; i++) {
                const assignment = await apiClient.createReviewAssignment(
                    inReviewJournal.id,
                    otherManuscripts[i].id,
                    createReviewAssignmentPayload({ required_expertise: 'Medieval History' }),
                    sectionEditorHeaders
                ).then(res => handleApiResponse<ReviewAssignment>(res, 201));

                await apiClient.inviteReviewer(
                    inReviewJournal.id,
                    createReviewInvitationPayload(assignment.id, reviewer.id),
                    sectionEditorHeaders
                ).then(res => handleApiResponse<Review>(res, 201));
            }

            const assignment = await apiClient.createReviewAssignment(
                inReviewJournal.id,
                manuscript.id,
                createReviewAssignmentPayload({ required_expertise: 'Quantum Mechanics' }),
                sectionEditorHeaders
            ).then(res => handleApiResponse<ReviewAssignment>(res, 201));

            const inviteRes = await apiClient.inviteReviewer(
                inReviewJournal.id,
                createReviewInvitationPayload(assignment.id, reviewer.id),
                sectionEditorHeaders
            );

            validateErrorEnvelope(inviteRes, { expectedErrorId: ApiErrorId.ERR_EXPERTISE_MISMATCH });
        });

        it('should return ERR_INSTITUTIONAL_CONFLICT when both conflict and risk threshold are violated', async () => {
            const journal = await setupJournal({ total_prestige: 100 });

            for (let i = 0; i < 16; i++) {
                await apiClient.createManuscript(journal.id, {
                    title: `Fast Track ${i}`,
                    submission_date: Math.floor(Date.now() / 1000),
                    is_fast_track_submission: true
                }, sectionEditorHeaders);
            }

            const journalWithRisk = await apiClient.getJournal(journal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));
            expect(journalWithRisk.desk_reject_risk_score).toBe(80);

            const manuscript = await setupManuscript(journal.id);

            const inReviewJournal = await apiClient.beginReview(journal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));

            const reviewer = await setupReviewerProfile(inReviewJournal.id, { institution: 'Test University' });

            await apiClient.createConflictOfInterest(inReviewJournal.id, {
                entity_1_id: reviewer.id,
                entity_2_id: 'Test University',
                conflict_type: ConflictOfInterestType.INSTITUTIONAL,
                reason: 'Same institution'
            }, journalEditorHeaders);

            for (let i = 0; i < 3; i++) {
                await apiClient.createReviewAssignment(
                    inReviewJournal.id,
                    manuscript.id,
                    createReviewAssignmentPayload(),
                    sectionEditorHeaders
                );
            }

            const extraAssignment = await apiClient.createReviewAssignment(
                inReviewJournal.id,
                manuscript.id,
                createReviewAssignmentPayload(),
                sectionEditorHeaders
            ).then(res => handleApiResponse<ReviewAssignment>(res, 201));

            await apiClient.updateManuscript(
                inReviewJournal.id,
                manuscript.id,
                { status: ManuscriptStatus.PENDING_REVIEW },
                journalEditorHeaders
            );

            const inviteRes = await apiClient.inviteReviewer(
                inReviewJournal.id,
                createReviewInvitationPayload(extraAssignment.id, reviewer.id),
                sectionEditorHeaders
            );

            validateErrorEnvelope(inviteRes, { expectedErrorId: ApiErrorId.ERR_RISK_THRESHOLD_BREACHED });
        });

        it('should return ERR_PRIOR_COLLABORATION when both prior collaboration conflict and insufficient prestige exist', async () => {
            const journalWithLowPrestige = await setupJournal({ total_prestige: 10 });
            const manuscriptForPrestigeTest = await setupManuscript(journalWithLowPrestige.id);

            const reviewerForPrestigeTest = await setupReviewerProfile(journalWithLowPrestige.id);
            const collaboratorForPrestigeTest = await setupReviewerProfile(journalWithLowPrestige.id);

            await apiClient.createConflictOfInterest(journalWithLowPrestige.id, {
                entity_1_id: reviewerForPrestigeTest.id,
                entity_2_id: collaboratorForPrestigeTest.id,
                conflict_type: ConflictOfInterestType.PRIOR_COLLABORATION,
                reason: 'Co-authored papers'
            }, journalEditorHeaders);

            const inReviewJournalWithLowPrestige = await apiClient.beginReview(journalWithLowPrestige.id, journalEditorHeaders)
              .then(res => handleApiResponse<Journal>(res, 200));

            const assignment = await apiClient.createReviewAssignment(
              inReviewJournalWithLowPrestige.id,
              manuscriptForPrestigeTest.id,
              createReviewAssignmentPayload(),
              sectionEditorHeaders
            ).then(res => handleApiResponse<ReviewAssignment>(res, 201));

            await apiClient.updateManuscript(
              inReviewJournalWithLowPrestige.id,
              manuscriptForPrestigeTest.id,
              { status: ManuscriptStatus.PENDING_REVIEW },
              journalEditorHeaders
            );

            const inviteRes = await apiClient.inviteReviewer(
              inReviewJournalWithLowPrestige.id,
              createReviewInvitationPayload(assignment.id, reviewerForPrestigeTest.id),
              sectionEditorHeaders
            );

            validateErrorEnvelope(inviteRes, { expectedErrorId: ApiErrorId.ERR_PRIOR_COLLABORATION });
        });

        it('should return ERR_PRIOR_COLLABORATION when both prior collaboration conflict and risk threshold are violated', async () => {
            const journal = await setupJournal({ total_prestige: 100 });

            for (let i = 0; i < 16; i++) {
                await apiClient.createManuscript(journal.id, {
                    title: `Fast Track ${i}`,
                    submission_date: Math.floor(Date.now() / 1000),
                    is_fast_track_submission: true
                }, sectionEditorHeaders);
            }

            const manuscript = await setupManuscript(journal.id);
            const inReviewJournal = await apiClient.beginReview(journal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));

            const reviewer = await setupReviewerProfile(inReviewJournal.id);
            const collaborator = await setupReviewerProfile(inReviewJournal.id);

            await apiClient.createConflictOfInterest(inReviewJournal.id, {
                entity_1_id: reviewer.id,
                entity_2_id: collaborator.id,
                conflict_type: ConflictOfInterestType.PRIOR_COLLABORATION,
                reason: 'Co-authored papers'
            }, journalEditorHeaders);

            for (let i = 0; i < 3; i++) {
                await apiClient.createReviewAssignment(
                    inReviewJournal.id,
                    manuscript.id,
                    createReviewAssignmentPayload(),
                    sectionEditorHeaders
                );
            }

            const extraAssignment = await apiClient.createReviewAssignment(
                inReviewJournal.id,
                manuscript.id,
                createReviewAssignmentPayload(),
                sectionEditorHeaders
            ).then(res => handleApiResponse<ReviewAssignment>(res, 201));

            await apiClient.updateManuscript(
                inReviewJournal.id,
                manuscript.id,
                { status: ManuscriptStatus.PENDING_REVIEW },
                journalEditorHeaders
            );

            const inviteRes = await apiClient.inviteReviewer(
                inReviewJournal.id,
                createReviewInvitationPayload(extraAssignment.id, reviewer.id),
                sectionEditorHeaders
            );

            validateErrorEnvelope(inviteRes, { expectedErrorId: ApiErrorId.ERR_PRIOR_COLLABORATION });
        });

        it('should return ERR_REVIEWER_OVERLOADED when both concurrency limit and risk threshold are violated', async () => {
            const journal = await setupJournal({ total_prestige: 100 });

            for (let i = 0; i < 16; i++) {
                await apiClient.createManuscript(journal.id, {
                    title: `Fast Track ${i}`,
                    submission_date: Math.floor(Date.now() / 1000),
                    is_fast_track_submission: true
                }, sectionEditorHeaders);
            }

            const manuscript = await setupManuscript(journal.id);
            const reviewer = await setupReviewerProfile(journal.id);

            const otherManuscripts: Manuscript[] = [];
            for (let i = 0; i < 5; i++) {
                const ms = await setupManuscript(journal.id);
                otherManuscripts.push(ms);
            }

            const inReviewJournal = await apiClient.beginReview(journal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));

            for (let i = 0; i < 5; i++) {
                const assignment = await apiClient.createReviewAssignment(
                    inReviewJournal.id,
                    otherManuscripts[i].id,
                    createReviewAssignmentPayload(),
                    sectionEditorHeaders
                ).then(res => handleApiResponse<ReviewAssignment>(res, 201));

                await apiClient.inviteReviewer(
                    inReviewJournal.id,
                    createReviewInvitationPayload(assignment.id, reviewer.id),
                    sectionEditorHeaders
                );
            }

            for (let i = 0; i < 3; i++) {
                await apiClient.createReviewAssignment(
                    inReviewJournal.id,
                    manuscript.id,
                    createReviewAssignmentPayload(),
                    sectionEditorHeaders
                );
            }

            const extraAssignment = await apiClient.createReviewAssignment(
                inReviewJournal.id,
                manuscript.id,
                createReviewAssignmentPayload(),
                sectionEditorHeaders
            ).then(res => handleApiResponse<ReviewAssignment>(res, 201));

            await apiClient.updateManuscript(
                inReviewJournal.id,
                manuscript.id,
                { status: ManuscriptStatus.PENDING_REVIEW },
                journalEditorHeaders
            );

            const inviteRes = await apiClient.inviteReviewer(
                inReviewJournal.id,
                createReviewInvitationPayload(extraAssignment.id, reviewer.id),
                sectionEditorHeaders
            );

            validateErrorEnvelope(inviteRes, { expectedErrorId: ApiErrorId.ERR_REVIEWER_OVERLOADED });
        });
    });

    describe('Prestige Ledger Boundary Tests', () => {

        it('should fail manuscript submission to PENDING_REVIEW with insufficient prestige', async () => {
            const journal = await setupJournal({ total_prestige: 5 });
            const manuscript = await setupManuscript(journal.id);

            const inReviewJournal = await apiClient.beginReview(journal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));

            await apiClient.createReviewAssignment(
                inReviewJournal.id,
                manuscript.id,
                createReviewAssignmentPayload(),
                sectionEditorHeaders
            );

            const updateRes = await apiClient.updateManuscript(
                inReviewJournal.id,
                manuscript.id,
                { status: ManuscriptStatus.PENDING_REVIEW },
                journalEditorHeaders
            );

            validateErrorEnvelope(updateRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_PRESTIGE });

            const manuscriptCheck = await apiClient.getManuscript(inReviewJournal.id, manuscript.id, journalEditorHeaders)
                .then(res => handleApiResponse<Manuscript>(res, 200));
            expect(manuscriptCheck.status).toBe(ManuscriptStatus.DRAFT);
        });

        it('should reject manuscript creation if risk score is already 100', async () => {
            const journal = await setupJournal({ total_prestige: 100 });

            for (let i = 0; i < 20; i++) {
                await apiClient.createManuscript(journal.id, {
                    title: `Fast Track Setup ${i}`,
                    submission_date: Math.floor(Date.now() / 1000),
                    is_fast_track_submission: true
                }, sectionEditorHeaders);
            }

            const journalWithRisk = await apiClient.getJournal(journal.id, journalEditorHeaders)
              .then(res => handleApiResponse<Journal>(res, 200));
            expect(journalWithRisk.desk_reject_risk_score).toBe(100);

            const secondRes = await apiClient.createManuscript(journal.id, {
                title: 'Second Paper',
                submission_date: Math.floor(Date.now() / 1000)
            }, sectionEditorHeaders);

            validateErrorEnvelope(secondRes, { expectedErrorId: ApiErrorId.ERR_RISK_SCORE_TOO_HIGH });
        });
    });

    describe('Complex State Management', () => {
        it('should correctly handle cascading cancellation of reviews in mixed states', async () => {
            const journal = await setupJournal({ total_prestige: 100 });
            const manuscript = await setupManuscript(journal.id);

            const inReviewJournal = await apiClient.beginReview(journal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));

            const reviewer = await setupReviewerProfile(inReviewJournal.id);

            const assignments: ReviewAssignment[] = [];
            for (let i = 0; i < 4; i++) {
                const assignment = await apiClient.createReviewAssignment(
                    inReviewJournal.id,
                    manuscript.id,
                    createReviewAssignmentPayload(),
                    sectionEditorHeaders
                ).then(res => handleApiResponse<ReviewAssignment>(res, 201));
                assignments.push(assignment);
            }

            await apiClient.updateManuscript(
                inReviewJournal.id,
                manuscript.id,
                { status: ManuscriptStatus.PENDING_REVIEW },
                journalEditorHeaders
            );

            const review1 = await apiClient.inviteReviewer(
                inReviewJournal.id,
                createReviewInvitationPayload(assignments[0].id, reviewer.id),
                sectionEditorHeaders
            ).then(res => handleApiResponse<Review>(res, 201));

            const review2 = await apiClient.inviteReviewer(
                inReviewJournal.id,
                createReviewInvitationPayload(assignments[1].id, reviewer.id),
                sectionEditorHeaders
            ).then(res => handleApiResponse<Review>(res, 201));
            await apiClient.acceptReview(inReviewJournal.id, review2.id, journalEditorHeaders);

            const review3 = await apiClient.inviteReviewer(
                inReviewJournal.id,
                createReviewInvitationPayload(assignments[2].id, reviewer.id),
                sectionEditorHeaders
            ).then(res => handleApiResponse<Review>(res, 201));
            await apiClient.acceptReview(inReviewJournal.id, review3.id, journalEditorHeaders);
            await apiClient.submitReview(inReviewJournal.id, review3.id, journalEditorHeaders);

            const review4 = await apiClient.inviteReviewer(
                inReviewJournal.id,
                createReviewInvitationPayload(assignments[3].id, reviewer.id),
                sectionEditorHeaders
            ).then(res => handleApiResponse<Review>(res, 201));

            const journalBeforeRejection = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));
            const prestigeBeforeRejection = journalBeforeRejection.prestige_balance;
            const riskBeforeRejection = journalBeforeRejection.desk_reject_risk_score;

            await apiClient.updateManuscript(
                inReviewJournal.id,
                manuscript.id,
                { status: ManuscriptStatus.REJECTED },
                journalEditorHeaders
            );

            const reviewsAfter = await Promise.all([
                apiClient.getReview(inReviewJournal.id, review1.id, journalEditorHeaders)
                    .then(res => handleApiResponse<Review>(res, 200)),
                apiClient.getReview(inReviewJournal.id, review2.id, journalEditorHeaders)
                    .then(res => handleApiResponse<Review>(res, 200)),
                apiClient.getReview(inReviewJournal.id, review3.id, journalEditorHeaders)
                    .then(res => handleApiResponse<Review>(res, 200)),
                apiClient.getReview(inReviewJournal.id, review4.id, journalEditorHeaders)
                    .then(res => handleApiResponse<Review>(res, 200))
            ]);

            reviewsAfter.forEach(review => {
                expect(review.status).toBe(ReviewStatus.CANCELLED);
            });

            const journalAfterRejection = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));

            expect(journalAfterRejection.prestige_balance).toBe(90);

            expect(journalAfterRejection.desk_reject_risk_score).toBe(0);
        });

        it('should count cancelled assignments towards revision quota', async () => {
            const journal = await setupJournal();
            const manuscript = await setupManuscript(journal.id);

            const inReviewJournal = await apiClient.beginReview(journal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));

            const reviewer = await setupReviewerProfile(inReviewJournal.id);

            for (let i = 0; i < 2; i++) {
                const assignment = await apiClient.createReviewAssignment(
                    inReviewJournal.id,
                    manuscript.id,
                    createReviewAssignmentPayload(),
                    sectionEditorHeaders
                ).then(res => handleApiResponse<ReviewAssignment>(res, 201));

                await apiClient.cancelReviewAssignment(
                    inReviewJournal.id,
                    manuscript.id,
                    assignment.id,
                    sectionEditorHeaders
                );
            }

            const assignment3 = await apiClient.createReviewAssignment(
                inReviewJournal.id,
                manuscript.id,
                createReviewAssignmentPayload(),
                sectionEditorHeaders
            ).then(res => handleApiResponse<ReviewAssignment>(res, 201));

            const assignment4 = await apiClient.createReviewAssignment(
                inReviewJournal.id,
                manuscript.id,
                createReviewAssignmentPayload(),
                sectionEditorHeaders
            ).then(res => handleApiResponse<ReviewAssignment>(res, 201));

            await apiClient.updateManuscript(
                inReviewJournal.id,
                manuscript.id,
                { status: ManuscriptStatus.PENDING_REVIEW },
                journalEditorHeaders
            );

            const assignment5 = await apiClient.createReviewAssignment(
                inReviewJournal.id,
                manuscript.id,
                createReviewAssignmentPayload(),
                sectionEditorHeaders
            ).then(res => handleApiResponse<ReviewAssignment>(res, 201));

            const inviteRes = await apiClient.inviteReviewer(
                inReviewJournal.id,
                createReviewInvitationPayload(assignment5.id, reviewer.id),
                sectionEditorHeaders
            );
            const review = handleApiResponse<Review>(inviteRes, 201);

            expect(review.in_extra_revision_cycle).toBe(true);
            expect(review.provisional_prestige_cost).toBe(1.5);

            const journalAfter = await apiClient.getJournal(journal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));
            expect(journalAfter.desk_reject_risk_score).toBe(20);
        });

        it('should still count assignments towards revision quota if their reviews are declined', async () => {
            const journal = await setupJournal();
            const manuscript = await setupManuscript(journal.id);

            const inReviewJournal = await apiClient.beginReview(journal.id, journalEditorHeaders)
              .then(res => handleApiResponse<Journal>(res, 200));

            const reviewer = await setupReviewerProfile(inReviewJournal.id);

            for (let i = 0; i < 3; i++) {
                const assignment = await apiClient.createReviewAssignment(
                  inReviewJournal.id,
                  manuscript.id,
                  createReviewAssignmentPayload(),
                  sectionEditorHeaders
                ).then(res => handleApiResponse<ReviewAssignment>(res, 201));

                const review = await apiClient.inviteReviewer(
                  inReviewJournal.id,
                  createReviewInvitationPayload(assignment.id, reviewer.id),
                  sectionEditorHeaders
                ).then(res => handleApiResponse<Review>(res, 201));

                await apiClient.declineReview(inReviewJournal.id, review.id, journalEditorHeaders);
            }

            await apiClient.updateManuscript(
              inReviewJournal.id,
              manuscript.id,
              { status: ManuscriptStatus.PENDING_REVIEW },
              journalEditorHeaders
            );

            const extraAssignment = await apiClient.createReviewAssignment(
              inReviewJournal.id,
              manuscript.id,
              createReviewAssignmentPayload(),
              sectionEditorHeaders
            ).then(res => handleApiResponse<ReviewAssignment>(res, 201));

            const inviteRes = await apiClient.inviteReviewer(
              inReviewJournal.id,
              createReviewInvitationPayload(extraAssignment.id, reviewer.id),
              sectionEditorHeaders
            );
            const review = handleApiResponse<Review>(inviteRes, 201);

            expect(review.in_extra_revision_cycle).toBe(true);
        });
    });

    describe('Reviewer Concurrency Management', () => {
        it('should immediately release concurrency slot when review is declined', async () => {
            const journal = await setupJournal();
            const manuscript = await setupManuscript(journal.id);
            const reviewer = await setupReviewerProfile(journal.id);

            const otherManuscripts: Manuscript[] = [];
            for (let i = 0; i < 5; i++) {
                const ms = await setupManuscript(journal.id);
                otherManuscripts.push(ms);
            }

            const inReviewJournal = await apiClient.beginReview(journal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));

            const reviews: Review[] = [];
            for (let i = 0; i < 5; i++) {
                const assignment = await apiClient.createReviewAssignment(
                    inReviewJournal.id,
                    otherManuscripts[i].id,
                    createReviewAssignmentPayload(),
                    sectionEditorHeaders
                ).then(res => handleApiResponse<ReviewAssignment>(res, 201));

                const review = await apiClient.inviteReviewer(
                    inReviewJournal.id,
                    createReviewInvitationPayload(assignment.id, reviewer.id),
                    sectionEditorHeaders
                ).then(res => handleApiResponse<Review>(res, 201));
                reviews.push(review);
            }

            const newAssignment = await apiClient.createReviewAssignment(
                inReviewJournal.id,
                manuscript.id,
                createReviewAssignmentPayload(),
                sectionEditorHeaders
            ).then(res => handleApiResponse<ReviewAssignment>(res, 201));

            const failedInviteRes = await apiClient.inviteReviewer(
                inReviewJournal.id,
                createReviewInvitationPayload(newAssignment.id, reviewer.id),
                sectionEditorHeaders
            );
            validateErrorEnvelope(failedInviteRes, { expectedErrorId: ApiErrorId.ERR_REVIEWER_OVERLOADED });

            await apiClient.declineReview(inReviewJournal.id, reviews[0].id, journalEditorHeaders);

            const successfulInviteRes = await apiClient.inviteReviewer(
                inReviewJournal.id,
                createReviewInvitationPayload(newAssignment.id, reviewer.id),
                sectionEditorHeaders
            );
            const newReview = handleApiResponse<Review>(successfulInviteRes, 201);
            expect(newReview.status).toBe(ReviewStatus.INVITED);
        });

        it('should not count SUBMITTED reviews toward concurrency limit', async () => {
            const journal = await setupJournal();
            const reviewer = await setupReviewerProfile(journal.id);

            const manuscripts: Manuscript[] = [];
            for (let i = 0; i < 6; i++) {
                const ms = await setupManuscript(journal.id);
                manuscripts.push(ms);
            }

            const inReviewJournal = await apiClient.beginReview(journal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));

            await apiClient.updateManuscript(
                inReviewJournal.id,
                manuscripts[0].id,
                { status: ManuscriptStatus.PENDING_REVIEW },
                journalEditorHeaders
            );

            for (let i = 0; i < 5; i++) {
                const assignment = await apiClient.createReviewAssignment(
                    inReviewJournal.id,
                    manuscripts[i].id,
                    createReviewAssignmentPayload(),
                    sectionEditorHeaders
                ).then(res => handleApiResponse<ReviewAssignment>(res, 201));

                const review = await apiClient.inviteReviewer(
                    inReviewJournal.id,
                    createReviewInvitationPayload(assignment.id, reviewer.id),
                    sectionEditorHeaders
                ).then(res => handleApiResponse<Review>(res, 201));

                await apiClient.acceptReview(inReviewJournal.id, review.id, journalEditorHeaders);
                await apiClient.submitReview(inReviewJournal.id, review.id, journalEditorHeaders);
            }

            const newAssignment = await apiClient.createReviewAssignment(
                inReviewJournal.id,
                manuscripts[5].id,
                createReviewAssignmentPayload(),
                sectionEditorHeaders
            ).then(res => handleApiResponse<ReviewAssignment>(res, 201));

            const newReviewRes = await apiClient.inviteReviewer(
                inReviewJournal.id,
                createReviewInvitationPayload(newAssignment.id, reviewer.id),
                sectionEditorHeaders
            );
            const newReview = handleApiResponse<Review>(newReviewRes, 201);
            expect(newReview.status).toBe(ReviewStatus.INVITED);
        });
    });

    describe('Post-Finalization Immutability', () => {
        it('should prevent all modifications to archived journal resources', async () => {
            const journal = await setupJournal();
            const manuscript = await setupManuscript(journal.id);

            const inReviewJournal = await apiClient.beginReview(journal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));

            const reviewer = await setupReviewerProfile(inReviewJournal.id);

            const assignment = await apiClient.createReviewAssignment(
                inReviewJournal.id,
                manuscript.id,
                createReviewAssignmentPayload(),
                sectionEditorHeaders
            ).then(res => handleApiResponse<ReviewAssignment>(res, 201));

            await apiClient.updateManuscript(
                inReviewJournal.id,
                manuscript.id,
                { status: ManuscriptStatus.PENDING_REVIEW },
                journalEditorHeaders
            );

            const review = await apiClient.inviteReviewer(
                inReviewJournal.id,
                createReviewInvitationPayload(assignment.id, reviewer.id),
                sectionEditorHeaders
            ).then(res => handleApiResponse<Review>(res, 201));

            await apiClient.acceptReview(inReviewJournal.id, review.id, journalEditorHeaders);
            await apiClient.submitReview(inReviewJournal.id, review.id, journalEditorHeaders);

            await apiClient.updateManuscript(
                inReviewJournal.id,
                manuscript.id,
                { status: ManuscriptStatus.ACCEPTED },
                journalEditorHeaders
            );

            await apiClient.initiatePublication(inReviewJournal.id, journalEditorHeaders);
            await apiClient.finalizePublication(inReviewJournal.id, managingEditorHeaders);

            const archivedJournal = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));
            expect(archivedJournal.status).toBe('ARCHIVED');

            const cancelReviewRes = await apiClient.cancelReview(inReviewJournal.id, review.id, journalEditorHeaders);
            validateErrorEnvelope(cancelReviewRes, { expectedErrorId: ApiErrorId.ERR_REVIEW_LIFECYCLE_STATE_INVALID });

            const newAssignmentRes = await apiClient.createReviewAssignment(
                inReviewJournal.id,
                manuscript.id,
                createReviewAssignmentPayload(),
                sectionEditorHeaders
            );
            validateErrorEnvelope(newAssignmentRes, { expectedErrorId: ApiErrorId.ERR_JOURNAL_NOT_IN_REVIEW });

            const updateManuscriptRes = await apiClient.updateManuscript(
                inReviewJournal.id,
                manuscript.id,
                { status: ManuscriptStatus.IN_REVISION },
                journalEditorHeaders
            );
            validateErrorEnvelope(updateManuscriptRes, { expectedErrorId: ApiErrorId.ERR_MANUSCRIPT_LIFECYCLE_STATE_INVALID });

            const readReview = await apiClient.getReview(inReviewJournal.id, review.id, journalEditorHeaders)
                .then(res => handleApiResponse<Review>(res, 200));
            expect(readReview.status).toBe(ReviewStatus.PUBLISHED);
            expect(readReview.final_prestige_cost).toBeDefined();

            const readManuscript = await apiClient.getManuscript(inReviewJournal.id, manuscript.id, journalEditorHeaders)
                .then(res => handleApiResponse<Manuscript>(res, 200));
            expect(readManuscript.status).toBe(ManuscriptStatus.ACCEPTED);
        });
    });

    describe('Manuscript Rejection Cascades', () => {
        it('should cascade cancel INVITED extra revision review and revert prestige/risk on manuscript rejection', async () => {
            const journal = await setupJournal({ total_prestige: 100 });
            const manuscript = await setupManuscript(journal.id);
            const reviewer = await setupReviewerProfile(journal.id);

            const inReviewJournal = await apiClient.beginReview(journal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));

            for (let i = 0; i < 3; i++) {
                await apiClient.createReviewAssignment(
                    inReviewJournal.id,
                    manuscript.id,
                    createReviewAssignmentPayload(),
                    sectionEditorHeaders
                );
            }

            const extraAssignment = await apiClient.createReviewAssignment(
                inReviewJournal.id,
                manuscript.id,
                createReviewAssignmentPayload(),
                sectionEditorHeaders
            ).then(res => handleApiResponse<ReviewAssignment>(res, 201));

            await apiClient.updateManuscript(
                inReviewJournal.id,
                manuscript.id,
                { status: ManuscriptStatus.PENDING_REVIEW },
                journalEditorHeaders
            );

            const review = await apiClient.inviteReviewer(
                inReviewJournal.id,
                createReviewInvitationPayload(extraAssignment.id, reviewer.id),
                sectionEditorHeaders
            ).then(res => handleApiResponse<Review>(res, 201));

            expect(review.in_extra_revision_cycle).toBe(true);
            expect(review.provisional_prestige_cost).toBe(1.5);

            const journalBeforeRejection = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));
            expect(journalBeforeRejection.prestige_balance).toBe(100 - 10 - 1.5);
            expect(journalBeforeRejection.desk_reject_risk_score).toBe(20);

            await apiClient.updateManuscript(
                inReviewJournal.id,
                manuscript.id,
                { status: ManuscriptStatus.REJECTED },
                journalEditorHeaders
            );

            const reviewAfter = await apiClient.getReview(inReviewJournal.id, review.id, journalEditorHeaders)
                .then(res => handleApiResponse<Review>(res, 200));
            expect(reviewAfter.status).toBe(ReviewStatus.CANCELLED);

            const assignmentAfter = await apiClient.getReviewAssignment(
                inReviewJournal.id,
                manuscript.id,
                extraAssignment.id,
                journalEditorHeaders
            ).then(res => handleApiResponse<ReviewAssignment>(res, 200));
            expect(assignmentAfter.status).toBe('PENDING_ASSIGNMENT');

            const journalAfter = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));
            expect(journalAfter.prestige_balance).toBe(90);
            expect(journalAfter.desk_reject_risk_score).toBe(0);
        });

        it('should cascade cancel ACCEPTED extra revision review and revert prestige/risk on manuscript rejection', async () => {
            const journal = await setupJournal({ total_prestige: 100 });
            const manuscript = await setupManuscript(journal.id);
            const reviewer = await setupReviewerProfile(journal.id);

            const inReviewJournal = await apiClient.beginReview(journal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));

            for (let i = 0; i < 3; i++) {
                await apiClient.createReviewAssignment(
                    inReviewJournal.id,
                    manuscript.id,
                    createReviewAssignmentPayload(),
                    sectionEditorHeaders
                );
            }

            const extraAssignment = await apiClient.createReviewAssignment(
                inReviewJournal.id,
                manuscript.id,
                createReviewAssignmentPayload(),
                sectionEditorHeaders
            ).then(res => handleApiResponse<ReviewAssignment>(res, 201));

            await apiClient.updateManuscript(
                inReviewJournal.id,
                manuscript.id,
                { status: ManuscriptStatus.PENDING_REVIEW },
                journalEditorHeaders
            );

            const review = await apiClient.inviteReviewer(
                inReviewJournal.id,
                createReviewInvitationPayload(extraAssignment.id, reviewer.id),
                sectionEditorHeaders
            ).then(res => handleApiResponse<Review>(res, 201));

            await apiClient.acceptReview(inReviewJournal.id, review.id, journalEditorHeaders);

            const journalBeforeRejection = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));
            expect(journalBeforeRejection.prestige_balance).toBe(100 - 10 - 1.5);
            expect(journalBeforeRejection.desk_reject_risk_score).toBe(20);

            await apiClient.updateManuscript(
                inReviewJournal.id,
                manuscript.id,
                { status: ManuscriptStatus.REJECTED },
                journalEditorHeaders
            );

            const reviewAfter = await apiClient.getReview(inReviewJournal.id, review.id, journalEditorHeaders)
                .then(res => handleApiResponse<Review>(res, 200));
            expect(reviewAfter.status).toBe(ReviewStatus.CANCELLED);

            const assignmentAfter = await apiClient.getReviewAssignment(
                inReviewJournal.id,
                manuscript.id,
                extraAssignment.id,
                journalEditorHeaders
            ).then(res => handleApiResponse<ReviewAssignment>(res, 200));
            expect(assignmentAfter.status).toBe('PENDING_ASSIGNMENT');

            const journalAfter = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));
            expect(journalAfter.prestige_balance).toBe(90);
            expect(journalAfter.desk_reject_risk_score).toBe(0);
        });

        it('should cascade cancel SUBMITTED extra revision review and revert prestige/risk on manuscript rejection', async () => {
            const journal = await setupJournal({ total_prestige: 100 });
            const manuscript = await setupManuscript(journal.id);
            const reviewer = await setupReviewerProfile(journal.id);

            const inReviewJournal = await apiClient.beginReview(journal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));

            for (let i = 0; i < 3; i++) {
                await apiClient.createReviewAssignment(
                    inReviewJournal.id,
                    manuscript.id,
                    createReviewAssignmentPayload(),
                    sectionEditorHeaders
                );
            }

            const extraAssignment = await apiClient.createReviewAssignment(
                inReviewJournal.id,
                manuscript.id,
                createReviewAssignmentPayload(),
                sectionEditorHeaders
            ).then(res => handleApiResponse<ReviewAssignment>(res, 201));

            await apiClient.updateManuscript(
                inReviewJournal.id,
                manuscript.id,
                { status: ManuscriptStatus.PENDING_REVIEW },
                journalEditorHeaders
            );

            const review = await apiClient.inviteReviewer(
                inReviewJournal.id,
                createReviewInvitationPayload(extraAssignment.id, reviewer.id),
                sectionEditorHeaders
            ).then(res => handleApiResponse<Review>(res, 201));

            await apiClient.acceptReview(inReviewJournal.id, review.id, journalEditorHeaders);
            await apiClient.submitReview(inReviewJournal.id, review.id, journalEditorHeaders);

            const submittedReview = await apiClient.getReview(inReviewJournal.id, review.id, journalEditorHeaders)
                .then(res => handleApiResponse<Review>(res, 200));
            expect(submittedReview.status).toBe(ReviewStatus.SUBMITTED);
            expect(submittedReview.final_prestige_cost).toBeNull();

            const journalBeforeRejection = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));
            expect(journalBeforeRejection.prestige_balance).toBe(100 - 10 - 1.5);
            expect(journalBeforeRejection.desk_reject_risk_score).toBe(20);

            await apiClient.updateManuscript(
                inReviewJournal.id,
                manuscript.id,
                { status: ManuscriptStatus.REJECTED },
                journalEditorHeaders
            );

            const reviewAfter = await apiClient.getReview(inReviewJournal.id, review.id, journalEditorHeaders)
                .then(res => handleApiResponse<Review>(res, 200));
            expect(reviewAfter.status).toBe(ReviewStatus.CANCELLED);

            const assignmentAfter = await apiClient.getReviewAssignment(
                inReviewJournal.id,
                manuscript.id,
                extraAssignment.id,
                journalEditorHeaders
            ).then(res => handleApiResponse<ReviewAssignment>(res, 200));
            expect(assignmentAfter.status).toBe('PENDING_ASSIGNMENT');

            const journalAfter = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));
            expect(journalAfter.prestige_balance).toBe(90);
            expect(journalAfter.desk_reject_risk_score).toBe(0);
        });
    });

    describe('Role-Based Access Control', () => {

        it('should reject finalization when attempted by JournalEditor', async () => {
            const journal = await setupJournal();
            const manuscript = await setupManuscript(journal.id);

            const inReviewJournal = await apiClient.beginReview(journal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));

            await apiClient.updateManuscript(
                inReviewJournal.id,
                manuscript.id,
                { status: ManuscriptStatus.ACCEPTED },
                journalEditorHeaders
            );

            await apiClient.initiatePublication(inReviewJournal.id, journalEditorHeaders);

            const finalizeRes = await apiClient.finalizePublication(inReviewJournal.id, journalEditorHeaders);
            validateErrorEnvelope(finalizeRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS });

            const journalCheck = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));
            expect(journalCheck.status).toBe('PUBLICATION_PENDING');
        });
    });

    describe('Journal State Constraints', () => {
        it('should reject manuscript creation unless journal is in ACCEPTING_SUBMISSIONS state', async () => {
            const journal = await setupJournal();
            const manuscriptForStateChange = await setupManuscript(journal.id);

            await apiClient.beginReview(journal.id, journalEditorHeaders);
            let createRes = await apiClient.createManuscript(journal.id, {
                title: 'Late Submission',
                submission_date: Math.floor(Date.now() / 1000)
            }, sectionEditorHeaders);
            validateErrorEnvelope(createRes, { expectedErrorId: ApiErrorId.ERR_JOURNAL_NOT_ACCEPTING_SUBMISSIONS });

            await apiClient.updateManuscript(
                journal.id,
                manuscriptForStateChange.id,
                { status: ManuscriptStatus.ACCEPTED },
                journalEditorHeaders
            );
            await apiClient.initiatePublication(journal.id, journalEditorHeaders);
            createRes = await apiClient.createManuscript(journal.id, {
                title: 'Too Late Submission',
                submission_date: Math.floor(Date.now() / 1000)
            }, sectionEditorHeaders);
            validateErrorEnvelope(createRes, { expectedErrorId: ApiErrorId.ERR_JOURNAL_NOT_ACCEPTING_SUBMISSIONS });

            await apiClient.finalizePublication(journal.id, managingEditorHeaders);
            createRes = await apiClient.createManuscript(journal.id, {
                title: 'Way Too Late Submission',
                submission_date: Math.floor(Date.now() / 1000)
            }, sectionEditorHeaders);
            validateErrorEnvelope(createRes, { expectedErrorId: ApiErrorId.ERR_JOURNAL_NOT_ACCEPTING_SUBMISSIONS });
        });
    });

    describe('Risk Score Threshold Boundaries', () => {
        it('should reject review invitation when projected risk exactly meets threshold (100)', async () => {
            const journal = await setupJournal({ total_prestige: 100 });

            for (let i = 0; i < 16; i++) {
                await apiClient.createManuscript(journal.id, {
                    title: `Fast Track ${i}`,
                    submission_date: Math.floor(Date.now() / 1000),
                    is_fast_track_submission: true
                }, sectionEditorHeaders);
            }

            const manuscript = await setupManuscript(journal.id);
            const reviewer = await setupReviewerProfile(journal.id);

            const inReviewJournal = await apiClient.beginReview(journal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));

            const journalCheck = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));
            expect(journalCheck.desk_reject_risk_score).toBe(80);

            for (let i = 0; i < 3; i++) {
                await apiClient.createReviewAssignment(
                    inReviewJournal.id,
                    manuscript.id,
                    createReviewAssignmentPayload(),
                    sectionEditorHeaders
                );
            }

            const extraAssignment = await apiClient.createReviewAssignment(
                inReviewJournal.id,
                manuscript.id,
                createReviewAssignmentPayload(),
                sectionEditorHeaders
            ).then(res => handleApiResponse<ReviewAssignment>(res, 201));

            await apiClient.updateManuscript(
                inReviewJournal.id,
                manuscript.id,
                { status: ManuscriptStatus.PENDING_REVIEW },
                journalEditorHeaders
            );

            const inviteRes = await apiClient.inviteReviewer(
                inReviewJournal.id,
                createReviewInvitationPayload(extraAssignment.id, reviewer.id),
                sectionEditorHeaders
            );

            validateErrorEnvelope(inviteRes, { expectedErrorId: ApiErrorId.ERR_RISK_THRESHOLD_BREACHED });

            const finalJournalCheck = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));
            expect(finalJournalCheck.desk_reject_risk_score).toBe(80);
            expect(finalJournalCheck.prestige_balance).toBe(90);
        });

        it('should allow new review after cancelling extra revision that would breach threshold', async () => {
            const journal = await setupJournal({ total_prestige: 100 });

            for (let i = 0; i < 15; i++) {
                await apiClient.createManuscript(journal.id, {
                    title: `Fast Track ${i}`,
                    submission_date: Math.floor(Date.now() / 1000),
                    is_fast_track_submission: true
                }, sectionEditorHeaders);
            }

            const manuscript = await setupManuscript(journal.id);
            const reviewer = await setupReviewerProfile(journal.id);

            const inReviewJournal = await apiClient.beginReview(journal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));

            for (let i = 0; i < 3; i++) {
                await apiClient.createReviewAssignment(
                    inReviewJournal.id,
                    manuscript.id,
                    createReviewAssignmentPayload(),
                    sectionEditorHeaders
                );
            }

            const extraAssignment = await apiClient.createReviewAssignment(
                inReviewJournal.id,
                manuscript.id,
                createReviewAssignmentPayload(),
                sectionEditorHeaders
            ).then(res => handleApiResponse<ReviewAssignment>(res, 201));

            await apiClient.updateManuscript(
                inReviewJournal.id,
                manuscript.id,
                { status: ManuscriptStatus.PENDING_REVIEW },
                journalEditorHeaders
            );

            const review = await apiClient.inviteReviewer(
                inReviewJournal.id,
                createReviewInvitationPayload(extraAssignment.id, reviewer.id),
                sectionEditorHeaders
            ).then(res => handleApiResponse<Review>(res, 201));

            const journalAt95 = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));
            expect(journalAt95.desk_reject_risk_score).toBe(95);

            await apiClient.cancelReview(inReviewJournal.id, review.id, journalEditorHeaders);

            const journalAfterCancel = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));
            expect(journalAfterCancel.desk_reject_risk_score).toBe(75);

            const assignmentAfterCancel = await apiClient.getReviewAssignment(
                inReviewJournal.id,
                manuscript.id,
                extraAssignment.id,
                journalEditorHeaders
            ).then(res => handleApiResponse<ReviewAssignment>(res, 200));
            expect(assignmentAfterCancel.status).toBe('PENDING_ASSIGNMENT');

            const newReviewer = await setupReviewerProfile(inReviewJournal.id);
            const newInviteRes = await apiClient.inviteReviewer(
                inReviewJournal.id,
                createReviewInvitationPayload(extraAssignment.id, newReviewer.id),
                sectionEditorHeaders
            );
            const newReview = handleApiResponse<Review>(newInviteRes, 201);
            expect(newReview.status).toBe(ReviewStatus.INVITED);
        });
    });

    describe('State Normalization After Rejection', () => {

        it('should correctly revert risk penalties when rejecting manuscript with extra revisions', async () => {
            const journal = await setupJournal({ total_prestige: 100 });

            for (let i = 0; i < 15; i++) {
                await apiClient.createManuscript(journal.id, {
                    title: `Fast Track ${i}`,
                    submission_date: Math.floor(Date.now() / 1000),
                    is_fast_track_submission: true
                }, sectionEditorHeaders);
            }

            const manuscript = await setupManuscript(journal.id);
            const reviewer = await setupReviewerProfile(journal.id);

            const inReviewJournal = await apiClient.beginReview(journal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));

            const journalAt75 = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));
            expect(journalAt75.desk_reject_risk_score).toBe(75);

            for (let i = 0; i < 3; i++) {
                await apiClient.createReviewAssignment(
                    inReviewJournal.id,
                    manuscript.id,
                    createReviewAssignmentPayload(),
                    sectionEditorHeaders
                );
            }

            const extraAssignment = await apiClient.createReviewAssignment(
                inReviewJournal.id,
                manuscript.id,
                createReviewAssignmentPayload(),
                sectionEditorHeaders
            ).then(res => handleApiResponse<ReviewAssignment>(res, 201));

            await apiClient.updateManuscript(
                inReviewJournal.id,
                manuscript.id,
                { status: ManuscriptStatus.PENDING_REVIEW },
                journalEditorHeaders
            );

            const review = await apiClient.inviteReviewer(
                inReviewJournal.id,
                createReviewInvitationPayload(extraAssignment.id, reviewer.id),
                sectionEditorHeaders
            ).then(res => handleApiResponse<Review>(res, 201));

            const journalAt95 = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));
            expect(journalAt95.desk_reject_risk_score).toBe(95);

            await apiClient.updateManuscript(
                inReviewJournal.id,
                manuscript.id,
                { status: ManuscriptStatus.REJECTED },
                journalEditorHeaders
            );

            const journalAfterReject = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders)
                .then(res => handleApiResponse<Journal>(res, 200));
            expect(journalAfterReject.desk_reject_risk_score).toBe(75);

            const reviewAfter = await apiClient.getReview(inReviewJournal.id, review.id, journalEditorHeaders)
                .then(res => handleApiResponse<Review>(res, 200));
            expect(reviewAfter.status).toBe(ReviewStatus.CANCELLED);

            const assignmentAfter = await apiClient.getReviewAssignment(
                inReviewJournal.id,
                manuscript.id,
                extraAssignment.id,
                journalEditorHeaders
            ).then(res => handleApiResponse<ReviewAssignment>(res, 200));
            expect(assignmentAfter.status).toBe('PENDING_ASSIGNMENT');
        });
    });
});
