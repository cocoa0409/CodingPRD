import {
    apiClient,
    buildUserHeaders,
    getSuccessData,
    handleApiResponse,
    validateErrorEnvelope,
    createJournalPayload, createReviewAssignmentPayload, createReviewInvitationPayload,
    Journal,
    Manuscript,
    ReviewAssignment,
    ReviewerProfile, JournalStatus,
    ManuscriptStatus, ReviewStatus,
    UserRole,
    ApiErrorId,
    setupInvitedReview,
    setupAcceptedReview,
    assertReview,
    setupJournal,
    setupManuscript,
    setupReviewerProfile
} from '../../../test-helpers';

describe('Phase 3: State Machine Transitions', () => {
    const journalEditorHeaders = buildUserHeaders('je-1', UserRole.JournalEditor);
    const sectionEditorHeaders = buildUserHeaders('se-1', UserRole.SectionEditor);
    const managingEditorHeaders = buildUserHeaders('me-1', UserRole.ManagingEditor);

    describe('Review State Machine', () => {
        let journal: Journal;
        let manuscript: Manuscript;
        let assignment: ReviewAssignment;
        let reviewer: ReviewerProfile;

        beforeEach(async () => {
            const plainJournal = await setupJournal();

            manuscript = await setupManuscript(plainJournal.id);
            reviewer = await setupReviewerProfile(plainJournal.id);

            const beginReviewRes = await apiClient.beginReview(plainJournal.id, journalEditorHeaders);
            journal = handleApiResponse(beginReviewRes, 200);
            const assignmentPayload = createReviewAssignmentPayload();
            const assignmentRes = await apiClient.createReviewAssignment(
                journal.id,
                manuscript.id,
                assignmentPayload,
                sectionEditorHeaders
            );
            assignment = getSuccessData(assignmentRes);
        });

        describe('Transition: accept_invitation (INVITED -> ACCEPTED)', () => {
            it('should transition review from INVITED to ACCEPTED', async () => {
                const invitationPayload = createReviewInvitationPayload(assignment.id, reviewer.id);
                const reviewRes = await apiClient.inviteReviewer(journal.id, invitationPayload, sectionEditorHeaders);
                const review = getSuccessData(reviewRes);
                expect(review.status).toBe(ReviewStatus.INVITED);

                const acceptRes = await apiClient.acceptReview(journal.id, review.id, journalEditorHeaders);
                const acceptedReview = handleApiResponse(acceptRes, 200);

                assertReview(acceptedReview);
                expect(acceptedReview.status).toBe(ReviewStatus.ACCEPTED);

                const getRes = await apiClient.getReview(journal.id, review.id, journalEditorHeaders);
                const retrievedReview = handleApiResponse(getRes, 200);
                expect(retrievedReview.status).toBe(ReviewStatus.ACCEPTED);
            });

            it('should fail when trying to accept a review that is already SUBMITTED', async () => {
                const { review, journal: localJournal } = await setupAcceptedReview();
                await apiClient.submitReview(localJournal.id, review.id, journalEditorHeaders);

                const submittedRes = await apiClient.getReview(localJournal.id, review.id, journalEditorHeaders);
                const submittedReview = handleApiResponse(submittedRes, 200);
                expect(submittedReview.status).toBe(ReviewStatus.SUBMITTED);

                const acceptRes = await apiClient.acceptReview(localJournal.id, review.id, journalEditorHeaders);

                validateErrorEnvelope(acceptRes, {
                    expectedErrorId: ApiErrorId.ERR_REVIEW_LIFECYCLE_STATE_INVALID,
                });

                const finalRes = await apiClient.getReview(localJournal.id, review.id, journalEditorHeaders);
                const finalReview = handleApiResponse(finalRes, 200);
                expect(finalReview.status).toBe(ReviewStatus.SUBMITTED);
            });
        });

        describe('Transition: decline_invitation (INVITED -> DECLINED)', () => {
            it('should transition review from INVITED to DECLINED', async () => {
                const invitationPayload = createReviewInvitationPayload(assignment.id, reviewer.id);
                const reviewRes = await apiClient.inviteReviewer(journal.id, invitationPayload, sectionEditorHeaders);
                const review = getSuccessData(reviewRes);
                expect(review.status).toBe(ReviewStatus.INVITED);

                const declineRes = await apiClient.declineReview(journal.id, review.id, journalEditorHeaders);
                const declinedReview = handleApiResponse(declineRes, 200);

                assertReview(declinedReview);
                expect(declinedReview.status).toBe(ReviewStatus.DECLINED);

                const getRes = await apiClient.getReview(journal.id, review.id, journalEditorHeaders);
                const retrievedReview = handleApiResponse(getRes, 200);
                expect(retrievedReview.status).toBe(ReviewStatus.DECLINED);
            });

            it('should revert assignment and refund prestige when a review is declined', async () => {
                const initialJournalRes = await apiClient.getJournal(journal.id, journalEditorHeaders);
                const initialJournal = getSuccessData(initialJournalRes);

                const invitationPayload = createReviewInvitationPayload(assignment.id, reviewer.id);
                const reviewRes = await apiClient.inviteReviewer(journal.id, invitationPayload, sectionEditorHeaders);
                const review = getSuccessData(reviewRes);

                const declineRes = await apiClient.declineReview(journal.id, review.id, journalEditorHeaders);
                handleApiResponse(declineRes, 200);

                const finalJournalRes = await apiClient.getJournal(journal.id, journalEditorHeaders);
                const finalJournal = getSuccessData(finalJournalRes);
                expect(finalJournal.prestige_balance).toBe(initialJournal.prestige_balance);

                const getAssignmentRes = await apiClient.getReviewAssignment(
                    journal.id,
                    manuscript.id,
                    assignment.id,
                    sectionEditorHeaders,
                );
                const updatedAssignment = getSuccessData(getAssignmentRes);
                expect(updatedAssignment.status).toBe('PENDING_ASSIGNMENT');
            });

            it('should fail when trying to decline an already accepted review', async () => {
                const { review, journal: localJournal } = await setupAcceptedReview();

                const acceptedRes = await apiClient.getReview(localJournal.id, review.id, journalEditorHeaders);
                const acceptedReview = handleApiResponse(acceptedRes, 200);
                expect(acceptedReview.status).toBe(ReviewStatus.ACCEPTED);

                const declineRes = await apiClient.declineReview(localJournal.id, review.id, journalEditorHeaders);

                validateErrorEnvelope(declineRes, {
                    expectedErrorId: ApiErrorId.ERR_REVIEW_LIFECYCLE_STATE_INVALID,
                });

                const finalRes = await apiClient.getReview(localJournal.id, review.id, journalEditorHeaders);
                const finalReview = handleApiResponse(finalRes, 200);
                expect(finalReview.status).toBe(ReviewStatus.ACCEPTED);
            });
        });

        describe('Transition: submit_review (ACCEPTED -> SUBMITTED)', () => {
            it('should transition review from ACCEPTED to SUBMITTED', async () => {
                const { review, journal: localJournal } = await setupAcceptedReview();

                const acceptedRes = await apiClient.getReview(localJournal.id, review.id, journalEditorHeaders);
                const acceptedReview = handleApiResponse(acceptedRes, 200);
                expect(acceptedReview.status).toBe(ReviewStatus.ACCEPTED);

                const submitRes = await apiClient.submitReview(localJournal.id, review.id, journalEditorHeaders);
                const submittedReview = handleApiResponse(submitRes, 200);

                assertReview(submittedReview);
                expect(submittedReview.status).toBe(ReviewStatus.SUBMITTED);

                const getRes = await apiClient.getReview(localJournal.id, review.id, journalEditorHeaders);
                const retrievedReview = handleApiResponse(getRes, 200);
                expect(retrievedReview.status).toBe(ReviewStatus.SUBMITTED);
            });

            it('should fail when trying to submit an invited review without accepting first', async () => {
                const { review, journal: localJournal } = await setupInvitedReview();
                expect(review.status).toBe(ReviewStatus.INVITED);

                const submitRes = await apiClient.submitReview(localJournal.id, review.id, journalEditorHeaders);

                validateErrorEnvelope(submitRes, {
                    expectedErrorId: ApiErrorId.ERR_REVIEW_LIFECYCLE_STATE_INVALID,
                });

                const finalRes = await apiClient.getReview(localJournal.id, review.id, journalEditorHeaders);
                const finalReview = handleApiResponse(finalRes, 200);
                expect(finalReview.status).toBe(ReviewStatus.INVITED);
            });
        });

        describe('Transition: cancel_review (INVITED/ACCEPTED/SUBMITTED -> CANCELLED)', () => {
            it('should transition review from SUBMITTED to CANCELLED', async () => {
                const { review, journal: localJournal } = await setupAcceptedReview();
                await apiClient.submitReview(localJournal.id, review.id, journalEditorHeaders);

                const submittedRes = await apiClient.getReview(localJournal.id, review.id, journalEditorHeaders);
                const submittedReview = handleApiResponse(submittedRes, 200);
                expect(submittedReview.status).toBe(ReviewStatus.SUBMITTED);

                const cancelRes = await apiClient.cancelReview(localJournal.id, review.id, journalEditorHeaders);
                const cancelledReview = handleApiResponse(cancelRes, 200);

                assertReview(cancelledReview);
                expect(cancelledReview.status).toBe(ReviewStatus.CANCELLED);

                const getRes = await apiClient.getReview(localJournal.id, review.id, journalEditorHeaders);
                const retrievedReview = handleApiResponse(getRes, 200);
                expect(retrievedReview.status).toBe(ReviewStatus.CANCELLED);
            });

            it('should revert assignment and refund prestige when a review is cancelled', async () => {
                const initialJournalRes = await apiClient.getJournal(journal.id, journalEditorHeaders);
                const initialJournal = getSuccessData(initialJournalRes);

                const assignmentPayload = createReviewAssignmentPayload();
                const assignmentRes = await apiClient.createReviewAssignment(
                    journal.id,
                    manuscript.id,
                    assignmentPayload,
                    sectionEditorHeaders,
                );
                const localAssignment = getSuccessData(assignmentRes);

                const localReviewer = await setupReviewerProfile(journal.id, { full_name: 'Temporary Reviewer' });

                const invitationPayload = createReviewInvitationPayload(localAssignment.id, localReviewer.id);
                const reviewRes = await apiClient.inviteReviewer(journal.id, invitationPayload, sectionEditorHeaders);
                const review = getSuccessData(reviewRes);

                await apiClient.acceptReview(journal.id, review.id, journalEditorHeaders);

                const cancelRes = await apiClient.cancelReview(journal.id, review.id, journalEditorHeaders);
                handleApiResponse(cancelRes, 200);

                const finalJournalRes = await apiClient.getJournal(journal.id, journalEditorHeaders);
                const finalJournal = getSuccessData(finalJournalRes);
                expect(finalJournal.prestige_balance).toBe(initialJournal.prestige_balance);

                const getAssignmentRes = await apiClient.getReviewAssignment(
                    journal.id,
                    manuscript.id,
                    localAssignment.id,
                    sectionEditorHeaders,
                );
                const updatedAssignment = getSuccessData(getAssignmentRes);
                expect(updatedAssignment.status).toBe('PENDING_ASSIGNMENT');
            });

            it('should fail when trying to cancel a PUBLISHED review', async () => {
                const { review, journal: localJournal } = await setupAcceptedReview();
                await apiClient.submitReview(localJournal.id, review.id, journalEditorHeaders);
                await apiClient.initiatePublication(localJournal.id, journalEditorHeaders);
                await apiClient.finalizePublication(localJournal.id, managingEditorHeaders);

                const publishedRes = await apiClient.getReview(localJournal.id, review.id, journalEditorHeaders);
                const publishedReview = handleApiResponse(publishedRes, 200);
                expect(publishedReview.status).toBe(ReviewStatus.PUBLISHED);

                const cancelRes = await apiClient.cancelReview(localJournal.id, review.id, journalEditorHeaders);

                validateErrorEnvelope(cancelRes, {
                    expectedErrorId: ApiErrorId.ERR_REVIEW_LIFECYCLE_STATE_INVALID,
                });

                const finalRes = await apiClient.getReview(localJournal.id, review.id, journalEditorHeaders);
                const finalReview = handleApiResponse(finalRes, 200);
                expect(finalReview.status).toBe(ReviewStatus.PUBLISHED);
            });
        });

        describe('Transition: mark_as_published (SUBMITTED -> PUBLISHED)', () => {
            it('should transition review to PUBLISHED and maintain prestige balance when publication is finalized', async () => {
                const { review, journal: localJournal } = await setupAcceptedReview();
                await apiClient.submitReview(localJournal.id, review.id, journalEditorHeaders);

                const submittedRes = await apiClient.getReview(localJournal.id, review.id, journalEditorHeaders);
                const submittedReview = handleApiResponse(submittedRes, 200);
                expect(submittedReview.status).toBe(ReviewStatus.SUBMITTED);

                const journalBeforeFinalizeRes = await apiClient.getJournal(localJournal.id, journalEditorHeaders);
                const journalBeforeFinalize = getSuccessData(journalBeforeFinalizeRes);
                const prestigeBalanceBefore = journalBeforeFinalize.prestige_balance;

                await apiClient.initiatePublication(localJournal.id, journalEditorHeaders);
                const finalizeRes = await apiClient.finalizePublication(localJournal.id, managingEditorHeaders);
                expect(finalizeRes.status).toBe(200);

                const getRes = await apiClient.getReview(localJournal.id, review.id, journalEditorHeaders);
                const publishedReview = handleApiResponse(getRes, 200);
                expect(publishedReview.status).toBe(ReviewStatus.PUBLISHED);

                const journalAfterFinalizeRes = await apiClient.getJournal(localJournal.id, journalEditorHeaders);
                const journalAfterFinalize = getSuccessData(journalAfterFinalizeRes);
                expect(journalAfterFinalize.prestige_balance).toBe(prestigeBalanceBefore);
                expect(journalAfterFinalize.status).toBe(JournalStatus.ARCHIVED);
            });

            it('should fail to initiate publication when a review is in ACCEPTED state', async () => {
                const { review, journal: localJournal, manuscript: localManuscript } = await setupAcceptedReview();

                const acceptedRes = await apiClient.getReview(localJournal.id, review.id, journalEditorHeaders);
                const acceptedReview = handleApiResponse(acceptedRes, 200);
                expect(acceptedReview.status).toBe(ReviewStatus.ACCEPTED);

                const plainJournal = await setupJournal();
                const manuscript2 = await setupManuscript(plainJournal.id);

                const beginReviewRes = await apiClient.beginReview(plainJournal.id, journalEditorHeaders);
                const reviewedJournal = handleApiResponse(beginReviewRes, 200);
                const assignment2Res = await apiClient.createReviewAssignment(reviewedJournal.id, manuscript2.id, createReviewAssignmentPayload(), sectionEditorHeaders);
                const assignment2 = getSuccessData(assignment2Res);
                const reviewer2 = await setupReviewerProfile(plainJournal.id, { full_name: 'Reviewer Two' });
                const invitation2Payload = createReviewInvitationPayload(assignment2.id, reviewer2.id);
                const review2Res = await apiClient.inviteReviewer(reviewedJournal.id, invitation2Payload, sectionEditorHeaders);
                const review2 = getSuccessData(review2Res);
                await apiClient.acceptReview(reviewedJournal.id, review2.id, journalEditorHeaders);
                await apiClient.submitReview(reviewedJournal.id, review2.id, journalEditorHeaders);

                const publicationRes = await apiClient.initiatePublication(localJournal.id, journalEditorHeaders);

                validateErrorEnvelope(publicationRes, {
                    expectedErrorId: ApiErrorId.ERR_UNRESOLVED_REVIEWS_EXIST,
                });

                const finalReviewRes = await apiClient.getReview(localJournal.id, review.id, journalEditorHeaders);
                const finalReview = handleApiResponse(finalReviewRes, 200);
                expect(finalReview.status).toBe(ReviewStatus.ACCEPTED);

                const journalRes = await apiClient.getJournal(localJournal.id, journalEditorHeaders);
                const updatedJournal = handleApiResponse(journalRes, 200);
                expect(updatedJournal.status).toBe(JournalStatus.IN_REVIEW);
            });
        });
    });

    describe('Additional State Transition Edge Cases', () => {
        let journal: Journal;
        let manuscript: Manuscript;
        let assignment: ReviewAssignment;
        let reviewer: ReviewerProfile;

        beforeEach(async () => {
            const plainJournal = await setupJournal();

            manuscript = await setupManuscript(plainJournal.id);

            const beginReviewRes = await apiClient.beginReview(plainJournal.id, journalEditorHeaders);
            journal = handleApiResponse(beginReviewRes, 200);
            const assignmentPayload = createReviewAssignmentPayload();
            const assignmentRes = await apiClient.createReviewAssignment(
                journal.id,
                manuscript.id,
                assignmentPayload,
                sectionEditorHeaders
            );
            assignment = getSuccessData(assignmentRes);
            reviewer = await setupReviewerProfile(plainJournal.id);
        });

        describe('Manuscript Readiness', () => {
            it('should fail to mark a manuscript as ready for review if it has no review assignments', async () => {
                const plainJournal = await setupJournal();
                const newManuscript = await setupManuscript(plainJournal.id, { title: 'Empty Manuscript' });

                const updateRes = await apiClient.updateManuscript(
                    plainJournal.id,
                    newManuscript.id,
                    { status: ManuscriptStatus.PENDING_REVIEW },
                    journalEditorHeaders
                );

                validateErrorEnvelope(updateRes, {
                    expectedErrorId: ApiErrorId.ERR_NO_ASSIGNMENTS,
                });
            });
        });

        describe('Review State Integrity', () => {
            it('should fail to accept a CANCELLED review', async () => {
                const { review, journal: localJournal } = await setupInvitedReview();
                await apiClient.cancelReview(localJournal.id, review.id, journalEditorHeaders);

                const acceptRes = await apiClient.acceptReview(localJournal.id, review.id, journalEditorHeaders);

                validateErrorEnvelope(acceptRes, {
                    expectedErrorId: ApiErrorId.ERR_REVIEW_LIFECYCLE_STATE_INVALID,
                });
            });

            it('should fail to submit a CANCELLED review', async () => {
                const { review, journal: localJournal } = await setupAcceptedReview();
                await apiClient.cancelReview(localJournal.id, review.id, journalEditorHeaders);

                const submitRes = await apiClient.submitReview(localJournal.id, review.id, journalEditorHeaders);

                validateErrorEnvelope(submitRes, {
                    expectedErrorId: ApiErrorId.ERR_REVIEW_LIFECYCLE_STATE_INVALID,
                });
            });

            it('should fail to cancel a DECLINED review', async () => {
                const { review, journal: localJournal } = await setupInvitedReview();
                await apiClient.declineReview(localJournal.id, review.id, journalEditorHeaders);

                const cancelRes = await apiClient.cancelReview(localJournal.id, review.id, journalEditorHeaders);

                validateErrorEnvelope(cancelRes, {
                    expectedErrorId: ApiErrorId.ERR_REVIEW_LIFECYCLE_STATE_INVALID,
                });
            });
        });

        describe('Journal State Integrity', () => {
            it('should fail to initiate publication if an INVITED review exists', async () => {
                const { journal: localJournal } = await setupInvitedReview();

                const publicationRes = await apiClient.initiatePublication(localJournal.id, journalEditorHeaders);

                validateErrorEnvelope(publicationRes, {
                    expectedErrorId: ApiErrorId.ERR_UNRESOLVED_REVIEWS_EXIST,
                });
            });

            it('should fail to begin review for an ARCHIVED journal', async () => {
                const plainJournal = await setupJournal();
                const manuscript = await setupManuscript(plainJournal.id);

                const beginReviewRes = await apiClient.beginReview(plainJournal.id, journalEditorHeaders);
                const journal = handleApiResponse(beginReviewRes, 200);
                const assignment = await apiClient.createReviewAssignment(journal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders);
                const reviewer = await setupReviewerProfile(plainJournal.id);
                const reviewRes = await apiClient.inviteReviewer(journal.id, createReviewInvitationPayload(getSuccessData(assignment).id, reviewer.id), sectionEditorHeaders);
                const review = getSuccessData(reviewRes);
                await apiClient.acceptReview(journal.id, review.id, journalEditorHeaders);
                await apiClient.submitReview(journal.id, review.id, journalEditorHeaders);
                await apiClient.initiatePublication(journal.id, journalEditorHeaders);
                await apiClient.finalizePublication(journal.id, managingEditorHeaders);

                const finalBeginReviewRes = await apiClient.beginReview(journal.id, journalEditorHeaders);

                validateErrorEnvelope(finalBeginReviewRes, {
                    expectedErrorId: ApiErrorId.ERR_JOURNAL_LIFECYCLE_STATE_INVALID,
                });
            });

            it('should fail to finalize publication for an ARCHIVED journal', async () => {
                await apiClient.initiatePublication(journal.id, journalEditorHeaders);
                await apiClient.finalizePublication(journal.id, managingEditorHeaders);

                const finalizeRes = await apiClient.finalizePublication(journal.id, managingEditorHeaders);

                validateErrorEnvelope(finalizeRes, {
                    expectedErrorId: ApiErrorId.ERR_JOURNAL_NOT_PENDING_PUBLICATION,
                });
            });
        });
    });

    describe('Further State Transition Integrity', () => {
        let journal: Journal;
        let manuscript: Manuscript;

        beforeEach(async () => {
            const plainJournal = await setupJournal();

            manuscript = await setupManuscript(plainJournal.id);

            const beginReviewRes = await apiClient.beginReview(plainJournal.id, journalEditorHeaders);
            journal = handleApiResponse(beginReviewRes, 200);
        });

        it('should fail to mark a manuscript that is already PENDING_REVIEW as ready again', async () => {
            const plainJournal = await setupJournal();
            const manuscript = await setupManuscript(plainJournal.id);
            await apiClient.beginReview(plainJournal.id, journalEditorHeaders);
            await apiClient.createReviewAssignment(plainJournal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders);
            await apiClient.updateManuscript(plainJournal.id, manuscript.id, { status: ManuscriptStatus.PENDING_REVIEW }, journalEditorHeaders);

            const updateAgainRes = await apiClient.updateManuscript(
                plainJournal.id,
                manuscript.id,
                { status: ManuscriptStatus.PENDING_REVIEW },
                journalEditorHeaders
            );

            validateErrorEnvelope(updateAgainRes, {
                expectedErrorId: ApiErrorId.ERR_MANUSCRIPT_LIFECYCLE_STATE_INVALID,
            });
        });
        it('should fail to invite a reviewer for a CANCELLED assignment', async () => {
            const plainJournal = await setupJournal();
            const manuscript = await setupManuscript(plainJournal.id);

            const beginReviewRes = await apiClient.beginReview(plainJournal.id, journalEditorHeaders);
            const journal = handleApiResponse(beginReviewRes, 200);
            const assignmentRes = await apiClient.createReviewAssignment(journal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders);
            const assignment = getSuccessData(assignmentRes);

            await apiClient.cancelReviewAssignment(journal.id, manuscript.id, assignment.id, sectionEditorHeaders);

            const reviewer = await setupReviewerProfile(plainJournal.id);

            const invitationRes = await apiClient.inviteReviewer(journal.id, createReviewInvitationPayload(assignment.id, reviewer.id), sectionEditorHeaders);

            validateErrorEnvelope(invitationRes, {
                expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING,
            });
        });

        it('should fail to initiate publication for a journal that is already PUBLICATION_PENDING', async () => {
            const plainJournal = await setupJournal();
            await apiClient.beginReview(plainJournal.id, journalEditorHeaders);
            await apiClient.initiatePublication(plainJournal.id, journalEditorHeaders);

            const publicationRes = await apiClient.initiatePublication(plainJournal.id, journalEditorHeaders);

            validateErrorEnvelope(publicationRes, {
                expectedErrorId: ApiErrorId.ERR_JOURNAL_LIFECYCLE_STATE_INVALID,
            });
        });

        it('should fail to initiate publication for an ARCHIVED journal', async () => {
            const plainJournal = await setupJournal();
            await apiClient.beginReview(plainJournal.id, journalEditorHeaders);
            await apiClient.initiatePublication(plainJournal.id, journalEditorHeaders);
            await apiClient.finalizePublication(plainJournal.id, managingEditorHeaders);

            const publicationRes = await apiClient.initiatePublication(plainJournal.id, journalEditorHeaders);

            validateErrorEnvelope(publicationRes, {
                expectedErrorId: ApiErrorId.ERR_JOURNAL_LIFECYCLE_STATE_INVALID,
            });
        });
    });

    describe('Cross-Resource State Integrity and Scoping', () => {
        let journal1: Journal;
        let journal2: Journal;

        beforeEach(async () => {
            const [res1, res2] = await Promise.all([
                apiClient.createJournal(createJournalPayload({ journal_name: 'Journal One' }), journalEditorHeaders),
                apiClient.createJournal(createJournalPayload({ journal_name: 'Journal Two' }), journalEditorHeaders),
            ]);
            journal1 = getSuccessData(res1);
            journal2 = getSuccessData(res2);

            await Promise.all([
                apiClient.beginReview(journal1.id, journalEditorHeaders),
                apiClient.beginReview(journal2.id, journalEditorHeaders),
            ]);
        });

        it('should cancel all reviews and refund costs when a manuscript is rejected', async () => {
            const plainJournal = await setupJournal({ total_prestige: 1000 });
            const manuscript = await setupManuscript(plainJournal.id, { is_fast_track_submission: true });

            await apiClient.beginReview(plainJournal.id, journalEditorHeaders);
            const journalRes = await apiClient.getJournal(plainJournal.id, journalEditorHeaders);
            const journal = getSuccessData(journalRes);

            const assignments = await Promise.all([
                apiClient.createReviewAssignment(journal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(getSuccessData),
                apiClient.createReviewAssignment(journal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(getSuccessData),
                apiClient.createReviewAssignment(journal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(getSuccessData),
                apiClient.createReviewAssignment(journal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(getSuccessData),
            ]);
            const reviewers = await Promise.all([
                setupReviewerProfile(journal.id, { full_name: 'Reviewer A' }),
                setupReviewerProfile(journal.id, { full_name: 'Reviewer B' }),
                setupReviewerProfile(journal.id, { full_name: 'Reviewer C' }),
                setupReviewerProfile(journal.id, { full_name: 'Reviewer D' }),
            ]);

            const reviews = await Promise.all(
                assignments.map((assignment, i) =>
                    apiClient.inviteReviewer(journal.id, createReviewInvitationPayload(assignment.id, reviewers[i].id), sectionEditorHeaders)
                        .then(getSuccessData)
                )
            );
            await apiClient.acceptReview(journal.id, reviews[0].id, journalEditorHeaders);
            await apiClient.acceptReview(journal.id, reviews[1].id, journalEditorHeaders);

            await apiClient.updateManuscript(journal.id, manuscript.id, { status: ManuscriptStatus.REJECTED }, journalEditorHeaders);

            const finalJournalRes = await apiClient.getJournal(journal.id, journalEditorHeaders);
            const finalJournal = getSuccessData(finalJournalRes);

            expect(finalJournal.prestige_balance).toBe(journal.total_prestige);
            expect(finalJournal.desk_reject_risk_score).toBe(0);

            for (const review of reviews) {
                const cancelledReviewRes = await apiClient.getReview(journal.id, review.id, journalEditorHeaders);
                const cancelledReview = handleApiResponse(cancelledReviewRes, 200);
                expect(cancelledReview.status).toBe(ReviewStatus.CANCELLED);
            }
        });

        it('should fail to submit a review if its parent manuscript was rejected', async () => {
            const plainJournal = await setupJournal();
            const manuscript = await setupManuscript(plainJournal.id);

            const beginReviewRes = await apiClient.beginReview(plainJournal.id, journalEditorHeaders);
            const journal = handleApiResponse(beginReviewRes, 200);
            const assignment = getSuccessData(await apiClient.createReviewAssignment(journal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders));
            const reviewer = await setupReviewerProfile(plainJournal.id);
            const review = getSuccessData(await apiClient.inviteReviewer(journal.id, createReviewInvitationPayload(assignment.id, reviewer.id), sectionEditorHeaders));
            await apiClient.acceptReview(journal.id, review.id, journalEditorHeaders);

            await apiClient.updateManuscript(journal.id, manuscript.id, { status: ManuscriptStatus.REJECTED }, journalEditorHeaders);

            const cancelledReviewRes = await apiClient.getReview(journal.id, review.id, journalEditorHeaders);
            const cancelledReview = handleApiResponse(cancelledReviewRes, 200);
            expect(cancelledReview.status).toBe(ReviewStatus.CANCELLED);

            const submitRes = await apiClient.submitReview(journal.id, review.id, journalEditorHeaders);

            validateErrorEnvelope(submitRes, {
                expectedErrorId: ApiErrorId.ERR_REVIEW_LIFECYCLE_STATE_INVALID,
            });
        });

        it('should fail to accept a review using the wrong journal ID', async () => {
            const plainJournal1 = await setupJournal();
            const manuscript1 = await setupManuscript(plainJournal1.id);

            const beginReviewRes1 = await apiClient.beginReview(plainJournal1.id, journalEditorHeaders);
            const journal1 = handleApiResponse(beginReviewRes1, 200);
            const assignment1 = getSuccessData(await apiClient.createReviewAssignment(journal1.id, manuscript1.id, createReviewAssignmentPayload(), sectionEditorHeaders));
            const reviewer1 = await setupReviewerProfile(plainJournal1.id);
            const review1 = getSuccessData(await apiClient.inviteReviewer(journal1.id, createReviewInvitationPayload(assignment1.id, reviewer1.id), sectionEditorHeaders));

            const plainJournal2 = await setupJournal();
            const beginReviewRes2 = await apiClient.beginReview(plainJournal2.id, journalEditorHeaders);
            const journal2 = handleApiResponse(beginReviewRes2, 200);

            const acceptRes = await apiClient.acceptReview(journal2.id, review1.id, journalEditorHeaders);

            validateErrorEnvelope(acceptRes, {
                expectedErrorId: ApiErrorId.ERR_REVIEW_NOT_FOUND,
            });
        });

        it('should fail to finalize publication for a journal in ACCEPTING_SUBMISSIONS state', async () => {
            const planningJournalRes = await apiClient.createJournal(createJournalPayload({ journal_name: 'Planning Only' }), journalEditorHeaders);
            const planningJournal = getSuccessData(planningJournalRes);

            const finalizeRes = await apiClient.finalizePublication(planningJournal.id, managingEditorHeaders);

            validateErrorEnvelope(finalizeRes, {
                expectedErrorId: ApiErrorId.ERR_JOURNAL_NOT_PENDING_PUBLICATION,
            });
        });
    });
});
