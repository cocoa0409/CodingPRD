import express from 'express';
import { requestContext } from './middleware/requestContext';
import { errorHandler } from './middleware/errorHandler';

import programRoutes from './routes/programs';
import trialRoutes from './routes/trials';
import portfolioRoutes from './routes/portfolios';
import dependencyRoutes from './routes/dependencies';
import phaseRoutes from './routes/phases';
import procedureRoutes from './routes/procedures';
import cohortRoutes from './routes/cohorts';
import executionRoutes from './routes/executions';
import irbRoutes from './routes/irbs';
import investigatorRoutes from './routes/investigators';
import otherRoutes from './routes/other';

const app = express();

app.use(express.json());

app.use(requestContext);

app.use('/research-programs', programRoutes);

app.use('/research-programs/:programId/clinical-trials', trialRoutes);

app.use('/research-programs/:programId/trial-portfolios', portfolioRoutes);

app.use(
  '/research-programs/:programId/clinical-trials/:trialId/dependencies',
  dependencyRoutes
);

app.use(
  '/research-programs/:programId/clinical-trials/:trialId/trial-phases',
  phaseRoutes
);

app.use(
  '/research-programs/:programId/clinical-trials/:trialId/trial-phases/:phaseId/protocol-procedures',
  procedureRoutes
);

app.use(
  '/research-programs/:programId/clinical-trials/:trialId/patient-cohorts',
  cohortRoutes
);

app.use(
  '/research-programs/:programId/clinical-trials/:trialId/procedure-executions',
  executionRoutes
);

app.use('/research-programs/:programId/irbs', irbRoutes);

app.use('/research-programs/:programId/investigators', investigatorRoutes);

app.use('/research-programs/:programId', otherRoutes);

app.use(errorHandler);

const PORT = process.env.PORT || 3000;

if (require.main === module) {
  app.listen(PORT, () => {
    console.log(`Clinical Trial Governance API listening on port ${PORT}`);
  });
}

export default app;
