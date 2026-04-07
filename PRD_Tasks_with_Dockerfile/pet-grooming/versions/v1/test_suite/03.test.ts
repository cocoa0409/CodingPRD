import {
    apiClient,
    buildUserHeaders,
    getSuccessData,
    handleApiResponse,
    validateErrorEnvelope,
    createAndActivateGroomingDay,
    createSessionBlock,
    createGroomingJob,
    createGroomerStation,
    createJobAssignment,
    confirmJobAssignment, GroomingDay,
    SessionBlock,
    GroomingJob,
    GroomerStation,
    JobAssignment,
    GroomingDayStatus,
    SessionBlockStatus,
    GroomingJobStatus,
    JobAssignmentStatus,
    UserRole,
    ApiErrorId,
    assertJobAssignment,
    generatePetId, RequiredAllergenType
} from '../../../test-helpers';

describe('Phase 2: State Machine Transitions', () => {
    const clinicManagerHeaders = buildUserHeaders('manager-1', UserRole.ClinicManager);
    const technicianHeaders = buildUserHeaders('technician-1', UserRole.GroomingTechnician);
    const billingAdminHeaders = buildUserHeaders('billing-1', UserRole.BillingAdmin);

    describe('Job Assignment State Machine', () => {
        let testDay: GroomingDay;
        let testBlock: SessionBlock;
        let testJob: GroomingJob;
        let testStation: GroomerStation;

        beforeEach(async () => {
            testDay = await createAndActivateGroomingDay('State Machine Test Day', 1000.0);

            testBlock = await createSessionBlock(testDay.id, 'State Machine Test Block', 1, 4);

            testJob = await createGroomingJob(
                testDay.id,
                testBlock.id,
                generatePetId(1),
                'Basic Grooming',
                1.5,
                60,
                { requiredAllergenType: RequiredAllergenType.NONE }
            );

            testStation = await createGroomerStation(
                testDay.id,
                'Test Station',
                'Standard',
                50.0
            );
        });

        describe('Transition: confirm_assignment', () => {

            it('should fail when trying to confirm an already confirmed assignment', async () => {
                const assignmentRes = await apiClient.createJobAssignment(
                    testDay.id,
                    { job_id: testJob.id, station_id: testStation.id },
                    technicianHeaders
                );
                const assignment = getSuccessData<JobAssignment>(assignmentRes);

                await apiClient.confirmJobAssignment(testDay.id, assignment.id, clinicManagerHeaders);

                const confirmedRes = await apiClient.getJobAssignment(testDay.id, assignment.id, clinicManagerHeaders);
                const confirmedAssignment = handleApiResponse<JobAssignment>(confirmedRes, 200);
                expect(confirmedAssignment.status).toBe(JobAssignmentStatus.CONFIRMED);

                const confirmAgainRes = await apiClient.confirmJobAssignment(
                    testDay.id,
                    assignment.id,
                    clinicManagerHeaders
                );

                validateErrorEnvelope(confirmAgainRes, {
                    expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PROPOSED
                });

                const finalRes = await apiClient.getJobAssignment(testDay.id, assignment.id, clinicManagerHeaders);
                const finalAssignment = handleApiResponse<JobAssignment>(finalRes, 200);
                expect(finalAssignment.status).toBe(JobAssignmentStatus.CONFIRMED);
            });
        });

        describe('Transition: terminate_assignment (PROPOSED/CONFIRMED -> TERMINATED)', () => {
            it('should transition assignment from CONFIRMED to TERMINATED', async () => {
                const assignmentRes = await apiClient.createJobAssignment(
                    testDay.id,
                    { job_id: testJob.id, station_id: testStation.id },
                    technicianHeaders
                );
                const assignment = getSuccessData<JobAssignment>(assignmentRes);

                await apiClient.confirmJobAssignment(testDay.id, assignment.id, clinicManagerHeaders);

                const confirmedRes = await apiClient.getJobAssignment(testDay.id, assignment.id, clinicManagerHeaders);
                const confirmedAssignment = handleApiResponse<JobAssignment>(confirmedRes, 200);
                expect(confirmedAssignment.status).toBe(JobAssignmentStatus.CONFIRMED);

                const terminateRes = await apiClient.terminateJobAssignment(
                    testDay.id,
                    assignment.id,
                    clinicManagerHeaders
                );
                const terminatedAssignment = handleApiResponse<JobAssignment>(terminateRes, 200);

                assertJobAssignment(terminatedAssignment);
                expect(terminatedAssignment.status).toBe(JobAssignmentStatus.TERMINATED);

                const getRes = await apiClient.getJobAssignment(testDay.id, assignment.id, clinicManagerHeaders);
                const retrievedAssignment = handleApiResponse<JobAssignment>(getRes, 200);
                expect(retrievedAssignment.status).toBe(JobAssignmentStatus.TERMINATED);
            });

            it('should fail when trying to terminate a completed assignment', async () => {
                const assignmentRes = await apiClient.createJobAssignment(
                    testDay.id,
                    { job_id: testJob.id, station_id: testStation.id },
                    technicianHeaders
                );
                const assignment = getSuccessData<JobAssignment>(assignmentRes);

                await apiClient.confirmJobAssignment(testDay.id, assignment.id, clinicManagerHeaders);

                await apiClient.initiateInvoicing(testDay.id, clinicManagerHeaders);
                await apiClient.generateInvoiceReport(testDay.id, billingAdminHeaders);

                const completedRes = await apiClient.getJobAssignment(testDay.id, assignment.id, clinicManagerHeaders);
                const completedAssignment = handleApiResponse<JobAssignment>(completedRes, 200);
                expect(completedAssignment.status).toBe(JobAssignmentStatus.COMPLETE);

                const terminateRes = await apiClient.terminateJobAssignment(
                    testDay.id,
                    assignment.id,
                    clinicManagerHeaders
                );

                validateErrorEnvelope(terminateRes, {
                    expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_TERMINABLE
                });

                const finalRes = await apiClient.getJobAssignment(testDay.id, assignment.id, clinicManagerHeaders);
                const finalAssignment = handleApiResponse<JobAssignment>(finalRes, 200);
                expect(finalAssignment.status).toBe(JobAssignmentStatus.COMPLETE);
            });
        });

        describe('Transition: confirm_assignment_direct (PROPOSED -> CONFIRMED)', () => {
            it('should transition assignment from PROPOSED to CONFIRMED directly', async () => {
                const assignmentRes = await apiClient.createJobAssignment(
                    testDay.id,
                    { job_id: testJob.id, station_id: testStation.id },
                    technicianHeaders
                );
                const assignment = getSuccessData<JobAssignment>(assignmentRes);
                expect(assignment.status).toBe(JobAssignmentStatus.PROPOSED);

                const confirmRes = await apiClient.confirmJobAssignment(
                    testDay.id,
                    assignment.id,
                    clinicManagerHeaders
                );
                const confirmedAssignment = handleApiResponse<JobAssignment>(confirmRes, 200);

                assertJobAssignment(confirmedAssignment);
                expect(confirmedAssignment.status).toBe(JobAssignmentStatus.CONFIRMED);

                const getRes = await apiClient.getJobAssignment(testDay.id, assignment.id, clinicManagerHeaders);
                const retrievedAssignment = handleApiResponse<JobAssignment>(getRes, 200);
                expect(retrievedAssignment.status).toBe(JobAssignmentStatus.CONFIRMED);
            });

            it('should fail when trying to confirm a proposed assignment without sufficient authority', async () => {
                const assignmentRes = await apiClient.createJobAssignment(
                    testDay.id,
                    { job_id: testJob.id, station_id: testStation.id },
                    technicianHeaders
                );
                const assignment = getSuccessData<JobAssignment>(assignmentRes);
                expect(assignment.status).toBe(JobAssignmentStatus.PROPOSED);

                const confirmRes = await apiClient.confirmJobAssignment(
                    testDay.id,
                    assignment.id,
                    technicianHeaders
                );

                validateErrorEnvelope(confirmRes, {
                    expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS
                });
            });
        });

        describe('Transition: mark_as_complete (CONFIRMED -> COMPLETE)', () => {
            it('should transition assignment from CONFIRMED to COMPLETE when invoice report is generated', async () => {
                const assignmentRes = await apiClient.createJobAssignment(
                    testDay.id,
                    { job_id: testJob.id, station_id: testStation.id },
                    technicianHeaders
                );
                const assignment = getSuccessData<JobAssignment>(assignmentRes);

                await apiClient.confirmJobAssignment(testDay.id, assignment.id, clinicManagerHeaders);

                const confirmedRes = await apiClient.getJobAssignment(testDay.id, assignment.id, clinicManagerHeaders);
                const confirmedAssignment = handleApiResponse<JobAssignment>(confirmedRes, 200);
                expect(confirmedAssignment.status).toBe(JobAssignmentStatus.CONFIRMED);

                await apiClient.initiateInvoicing(testDay.id, clinicManagerHeaders);

                const generateRes = await apiClient.generateInvoiceReport(testDay.id, billingAdminHeaders);
                expect(generateRes.status).toBe(200);

                const getRes = await apiClient.getJobAssignment(testDay.id, assignment.id, clinicManagerHeaders);
                const completedAssignment = handleApiResponse<JobAssignment>(getRes, 200);
                expect(completedAssignment.status).toBe(JobAssignmentStatus.COMPLETE);
            });

            it('should fail to initiate invoicing when an assignment is in PROPOSED state', async () => {
                const job = await createGroomingJob(
                    testDay.id,
                    testBlock.id,
                    generatePetId(60),
                    'Test Job',
                    2,
                    30
                );

                const assignmentRes = await apiClient.createJobAssignment(
                    testDay.id,
                    { job_id: job.id, station_id: testStation.id },
                    technicianHeaders
                );
                const assignment = getSuccessData<JobAssignment>(assignmentRes);
                expect(assignment.status).toBe(JobAssignmentStatus.PROPOSED);

                const billingRes = await apiClient.initiateInvoicing(testDay.id, clinicManagerHeaders);

                validateErrorEnvelope(billingRes, {
                    expectedErrorId: ApiErrorId.ERR_UNRESOLVED_ASSIGNMENTS_EXIST
                });

                const finalAssignmentRes = await apiClient.getJobAssignment(testDay.id, assignment.id, clinicManagerHeaders);
                const finalAssignment = handleApiResponse<JobAssignment>(finalAssignmentRes, 200);
                expect(finalAssignment.status).toBe(JobAssignmentStatus.PROPOSED);

                const dayRes = await apiClient.getGroomingDay(testDay.id, clinicManagerHeaders);
                const day = handleApiResponse<GroomingDay>(dayRes, 200);
                expect(day.status).toBe(GroomingDayStatus.ACTIVE);
            });
        });
    });

    describe('Further State Transition Integrity', () => {
        let day: GroomingDay;
        let block: SessionBlock;

        beforeEach(async () => {
            day = await createAndActivateGroomingDay('Integrity Test Day', 1000.0);
            block = await createSessionBlock(day.id, 'Integrity Test Block', 1, 4);
        });

        it('should fail to mark a block with zero jobs as ready', async () => {
            const updateRes = await apiClient.updateSessionBlockStatus(
                day.id,
                block.id,
                { status: SessionBlockStatus.READY_FOR_GROOMING },
                clinicManagerHeaders
            );

            validateErrorEnvelope(updateRes, {
                expectedErrorId: ApiErrorId.ERR_JOBS_NOT_CONFIRMED,
            });
        });

        it('should fail to mark a block that is already READY_FOR_GROOMING as ready again', async () => {
            const job = await createGroomingJob(day.id, block.id, generatePetId(200), 'Test Job', 1.5, 60);
            const station = await createGroomerStation(day.id, 'Test Station', 'Standard', 50.0);

            const assignment = await createJobAssignment(day.id, job.id, station.id);
            await confirmJobAssignment(day.id, assignment.id);

            await apiClient.updateSessionBlockStatus(
                day.id,
                block.id,
                { status: SessionBlockStatus.READY_FOR_GROOMING },
                clinicManagerHeaders
            );

            const updateAgainRes = await apiClient.updateSessionBlockStatus(
                day.id,
                block.id,
                { status: SessionBlockStatus.READY_FOR_GROOMING },
                clinicManagerHeaders
            );

            validateErrorEnvelope(updateAgainRes, {
                expectedErrorId: ApiErrorId.ERR_ILLEGAL_BLOCK_STATE_TRANSITION,
            });
        });

        it('should fail to propose an assignment to a CANCELLED job', async () => {
            const job = await createGroomingJob(day.id, block.id, generatePetId(300), 'Test Job', 1.5, 60);

            await apiClient.updateSessionBlockStatus(
                day.id,
                block.id,
                { status: SessionBlockStatus.CANCELLED },
                clinicManagerHeaders
            );

            const station = await createGroomerStation(day.id, 'Test Station', 'Standard', 50.0);

            const assignmentRes = await apiClient.createJobAssignment(
                day.id,
                { job_id: job.id, station_id: station.id },
                technicianHeaders
            );

            validateErrorEnvelope(assignmentRes, {
                expectedErrorId: ApiErrorId.ERR_JOB_NOT_PENDING,
            });
        });

        it('should fail to initiate invoicing for a day that is already INVOICING_PENDING', async () => {
            await apiClient.initiateInvoicing(day.id, clinicManagerHeaders);

            const billingRes = await apiClient.initiateInvoicing(day.id, clinicManagerHeaders);

            validateErrorEnvelope(billingRes, {
                expectedErrorId: ApiErrorId.ERR_DAY_NOT_ACTIVE,
            });
        });

        it('should fail to initiate invoicing for a CLOSED day', async () => {
            const job = await createGroomingJob(day.id, block.id, generatePetId(400), 'Test Job', 1.5, 60);
            const station = await createGroomerStation(day.id, 'Test Station', 'Standard', 50.0);
            const assignment = await createJobAssignment(day.id, job.id, station.id);
            await confirmJobAssignment(day.id, assignment.id);

            await apiClient.initiateInvoicing(day.id, clinicManagerHeaders);
            await apiClient.generateInvoiceReport(day.id, billingAdminHeaders);

            const billingRes = await apiClient.initiateInvoicing(day.id, clinicManagerHeaders);

            validateErrorEnvelope(billingRes, {
                expectedErrorId: ApiErrorId.ERR_DAY_NOT_ACTIVE,
            });
        });
    });

    describe('Cross-Resource State Integrity and Scoping', () => {
        let day1: GroomingDay;
        let day2: GroomingDay;

        beforeEach(async () => {
            day1 = await createAndActivateGroomingDay('Day One', 1000.0);
            day2 = await createAndActivateGroomingDay('Day Two', 1000.0);
        });

        it('should fail to confirm an assignment if its parent block was cancelled', async () => {
            const block = await createSessionBlock(day1.id, 'Test Block', 1, 4);
            const job = await createGroomingJob(day1.id, block.id, generatePetId(500), 'Test Job', 1.5, 60);
            const station = await createGroomerStation(day1.id, 'Test Station', 'Standard', 50.0);

            const assignmentRes = await apiClient.createJobAssignment(
                day1.id,
                { job_id: job.id, station_id: station.id },
                technicianHeaders
            );
            const assignment = getSuccessData<JobAssignment>(assignmentRes);

            await apiClient.updateSessionBlockStatus(
                day1.id,
                block.id,
                { status: SessionBlockStatus.CANCELLED },
                clinicManagerHeaders
            );

            const cancelledJobRes = await apiClient.getGroomingJob(day1.id, block.id, job.id, clinicManagerHeaders);
            const cancelledJob = handleApiResponse<GroomingJob>(cancelledJobRes, 200);
            expect(cancelledJob.status).toBe(GroomingJobStatus.CANCELLED);

            const cancelledAssignmentRes = await apiClient.getJobAssignment(day1.id, assignment.id, clinicManagerHeaders);
            const cancelledAssignment = handleApiResponse<JobAssignment>(cancelledAssignmentRes, 200);
            expect(cancelledAssignment.status).toBe(JobAssignmentStatus.TERMINATED);

            const confirmRes = await apiClient.confirmJobAssignment(day1.id, assignment.id, clinicManagerHeaders);

            validateErrorEnvelope(confirmRes, {
                expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PROPOSED,
            });
        });

        it('should fail to confirm an assignment using the wrong day ID', async () => {
            const block = await createSessionBlock(day1.id, 'Test Block', 1, 4);
            const job = await createGroomingJob(day1.id, block.id, generatePetId(600), 'Test Job', 1.5, 60);
            const station = await createGroomerStation(day1.id, 'Test Station', 'Standard', 50.0);

            const assignmentRes = await apiClient.createJobAssignment(
                day1.id,
                { job_id: job.id, station_id: station.id },
                technicianHeaders
            );
            const assignment = getSuccessData<JobAssignment>(assignmentRes);

            const confirmRes = await apiClient.confirmJobAssignment(day2.id, assignment.id, clinicManagerHeaders);

            validateErrorEnvelope(confirmRes, {
                expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND,
            });
        });

        it('should fail to generate invoice report for a day in PLANNING state', async () => {
            const planningDayRes = await apiClient.createGroomingDay(
                { schedule_name: 'Planning Only Day', total_supply_budget: 500.0 },
                clinicManagerHeaders
            );
            const planningDay = getSuccessData<GroomingDay>(planningDayRes);

            const generateRes = await apiClient.generateInvoiceReport(planningDay.id, billingAdminHeaders);

            validateErrorEnvelope(generateRes, {
                expectedErrorId: ApiErrorId.ERR_DAY_NOT_READY_FOR_INVOICING,
            });
        });
    });
});
