import express, { Request, Response, NextFunction } from 'express';

import tenantsRouter from './routes/tenants';
import listingsRouter from './routes/listings';
import ordersRouter from './routes/orders';
import workersRouter from './routes/workers';
import assignmentsRouter from './routes/assignments';
import payoutsRouter from './routes/payouts';
import disputesRouter from './routes/disputes';
import ratingsRouter from './routes/ratings';

const app = express();

app.use(express.json());

app.get('/', (req: Request, res: Response) => {
  res.json({ status: 'ok', message: 'Gig Marketplace Fulfillment API' });
});

app.use('/tenants', tenantsRouter);

app.use('/tenants/:tenantId/listings', listingsRouter);
app.use('/tenants/:tenantId/orders', ordersRouter);
app.use('/tenants/:tenantId/workers', workersRouter);

app.use('/tenants/:tenantId/orders/:orderId/assignments', assignmentsRouter);

app.use('/tenants/:tenantId/workers/:workerId/payouts', payoutsRouter);

app.use('/tenants/:tenantId/orders/:orderId/disputes', disputesRouter);

app.use('/tenants/:tenantId/orders/:orderId/ratings', ratingsRouter);

app.use((err: Error, req: Request, res: Response, next: NextFunction) => {
  console.error('Unhandled error:', err);
  res.status(500).json({
    meta: {
      api_request_id: 'error',
      api_request_period_index: 0
    },
    response_type: 'error',
    data: {
      error_id: 'ERR_INTERNAL_SERVER_ERROR',
      message: 'Internal server error'
    }
  });
});

app.use((req: Request, res: Response) => {
  res.status(404).json({
    meta: {
      api_request_id: 'not-found',
      api_request_period_index: 0
    },
    response_type: 'error',
    data: {
      error_id: 'ERR_NOT_FOUND',
      message: 'Endpoint not found'
    }
  });
});

const PORT = process.env.PORT || 3000;

app.listen(PORT, () => {
  console.log(`Gig Marketplace Fulfillment API running on port ${PORT}`);
});

export default app;
